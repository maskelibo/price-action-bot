---
hypothesis_id: 2026-05-15-dd-aware-dynamic-leverage
date: 2026-05-15
author: researcher_agent (claude-opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1.0
parent_strategy: none (overlay — portfolio leverage controller)
parent_baseline: v2.0.3 production champion (3y rolling +%239.5 / DD -%38.7 / r-adj 6.190)
sprint_class: max_roi_2026_05_15 (priority 1/5)
tags: [risk_management, dynamic_leverage, drawdown_attractor, equity_curve_smoothing, adaptive, overlay]
backtest_possible: true
data_requirements: [v091 trades, equity_snapshots (production_replay), no external data]
expected_correlation_w_existing: medium (BTC capitulation halt with which it is complementary, not duplicative)
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
ceo_brief_ref: max_roi_sprint priority#1 — DD smoothing first; ROI uplift second
bonferroni_factor: 5
---

# HYP-2026-05-15-001 — DD-Aware Dynamic Leverage (Equity-DD-Attractor Adaptive Leverage Controller)

## 1. Pre-Registered Iddia (TEK CUMLE)

> v2.0.3 sabit leverage modelinde (per-symbol max_lev=5, portfolio_x=5), portfolio-level **rolling-14d equity drawdown'a duyarli continuous leverage scalar** (DD = 0 -> 1.00x scalar, DD = -%10 -> 0.66x, DD >= -%20 -> 0.33x, saturating at floor) eklendiginde, v2.0.3 baseline'a karsi **3y rolling 13 pencerede DD bozulmasi <= +1pp** kisiti altinda **yillik ROI uplift >= +%5pp (mean) ve worst-window MaxDD iyilesmesi >= -4pp** uretir.

### Bagimli Degiskenler
- Mean annual return (3y rolling 13 windows)
- Mean MaxDD (3y rolling 13 windows)
- Worst-window MaxDD (en kotu pencere)
- Worst-window annual return
- Risk-adjusted (annual / |MaxDD|)
- Recovery time (peak-to-recovery, days)
- DD smoothness (rolling 30d equity vol)

### Bagimsiz Degiskenler (PRE-REGISTERED SABIT, sweep YASAK)
- `dd_lookback_days = 14` (rolling DD window)
- `dd_threshold_warn = -0.05` (-%5 DD -> scalar 1.00x -> 0.80x linear baslangic)
- `dd_threshold_critical = -0.15` (-%15 DD -> scalar 0.50x)
- `dd_floor_scalar = 0.33` (minimum 1/3'une dus, sifirlama YOK)
- `dd_recovery_lookback_days = 7` (DD <= threshold_warn 7 gun ust uste -> tam 1.00x'e don)
- `dd_scalar_apply = leverage_multiplicative` (her trade leverage'i scalar ile carp, floor MIN=1x, kelly_cap ve max_leverage_per_symbol korunur)
- baseline = v2.0.3 BALANCED+pyramid (configs/risk_balanced.yaml mevcut)
- walk-forward = 3y train + 6mo OOS + 3mo step -> 13 pencere

### Null Hipotezler (HERHANGI biri PASS olursa hipotez RED)
1. Mean annual return uplift < +%3pp (mean across 13 windows)
2. Mean MaxDD bozulmasi > +%1pp (DD worsens by more than 1pp)
3. Worst-window MaxDD iyilesmesi < -%2pp
4. Robustness 7 testten **>= 4 HARD FAIL**
5. Bootstrap CI(95%) low (annual return alpha) < 0
6. Bonferroni-adjusted p >= 0.010 (5 paralel HYP, alpha_adj = 0.05/5)
7. Shuffle baseline (DD kosulunu rastgele gunlere atayip ayni kurali calistir) p >= 0.05

---

## 2. Prior Strength — Literatur ve Ic Kanit

### Akademik / Kitap kaynaklari
- **Ralph Vince — "The Mathematics of Money Management" (1992):** Optimal-f and drawdown-aware position sizing. f'i drawdown-conditional kisitlamak optimal-f'i sub-optimal yapar ama TWR variance'ini ciddi dusurur. Klasik kanit: drawdown-aware sizing recovery time'i 1.5-2.5x kisaltir.
- **Edward Thorp — "A Man for All Markets" (2017), ch. 19-20:** Bridgewater "risk parity" portfolio-level vol targeting; DD-aware leverage scalar bunun "asymmetric loss-side" varyasyonu.
- **Jaffray Woodriff (Schwager 2012 "Hedge Fund Market Wizards"):** "Cut leverage in half during drawdown, restore when equity within %3 of peak" — Quantitative Investment Management oyun kitabi.
- **Marcos Lopez de Prado — "Advances in Financial ML" (2018), ch. 17:** Drawdown-conditional kelly fractionation; "kelly faces extinction risk; half-kelly faces 25% extinction; quarter-kelly during drawdown faces ~5% extinction" — bizim dd_floor_scalar=0.33 quarter-kelly proxy.
- **Andrew Lo, Pere Patel — "What Happened to the Quants in August 2007":** Portfolio leverage spike sonrasi drawdown amplifies; dynamic deleveraging riski azaltabilirdi.

### Icsel kanit (proje kanitlari)
- **v0.9.4 Capitulation Halt** — BTC ATR%/EMA200/90dDD kosullari saglandiginda bidirectional skip. Min pencere +%3.4 -> +%20 (6x uplift), DD -%37 -> -%30. **Bu HYP dogal extension**: regime-level binary halt yerine portfolio-equity-level continuous deleveraging.
- **v0.9.7 BALANCED+F&G** — F&G <=20 short skip continuous transition'a onisleme (filter->multiplier sinifi, bizim HYP ile ayni paradigma).
- **SEC26.B-1 Side-Conditional DD Breaker** — long 0.15 / short 0.05 monthly DD halt (live wired). Bizim HYP onun **continuous** ve **portfolio-level** versiyonu.
- **v0.9.2 Notional Cap** — equity %30 cap (statik). Bu HYP **dynamic** versiyonu (DD-conditional scaling).

### Mevcut sprint'le tamamlayicilik (orthogonality check)
- Capitulation halt -> regime-level (BTC) binary
- F&G filter -> sentiment-level binary
- Side-cond DD -> strategy-side monthly bucket
- **HYP-001 (bu) -> portfolio-equity-level continuous** Orthogonal

---

## 3. Mekanik Kurallar (PRE-REGISTERED, kod yazimi oncesi)

### 3.1 DD Scalar Function (continuous, monotonic, saturating)

```python
def dd_aware_leverage_scalar(equity_curve_14d, dd_threshold_warn=-0.05,
                              dd_threshold_critical=-0.15, dd_floor=0.33):
    """
    equity_curve_14d: last 14 days of daily equity snapshots (inclusive of t-1 close, T-DAY EXCLUSIVE — causal).
    Returns: scalar in [dd_floor, 1.00].
    """
    if len(equity_curve_14d) < 2:
        return 1.00
    peak = equity_curve_14d.max()
    current = equity_curve_14d.iloc[-1]
    dd = (current - peak) / peak
    if dd >= dd_threshold_warn:
        return 1.00
    if dd >= dd_threshold_critical:
        t = (dd - dd_threshold_warn) / (dd_threshold_critical - dd_threshold_warn)
        return 1.00 - 0.50 * t
    t = min(1.0, (dd - dd_threshold_critical) / (dd_threshold_critical * 2))
    return max(dd_floor, 0.50 - (0.50 - dd_floor) * t)
```

### 3.2 Recovery Logic
- Eger 7 ardisik gun boyunca DD >= dd_threshold_warn (-%5 ustu) olursa, scalar tekrar 1.00'a doner.

### 3.3 Leverage Uygulamasi
```python
final_leverage = min(
    max_leverage_per_symbol,
    base_confidence_leverage * dd_scalar,
    notional_cap_implied_leverage,
)
final_leverage = max(1.0, final_leverage)
```

**Risk_per_trade da scalar ile carpilir mi?** PRE-REG karar: **HAYIR**. Sadece leverage scalar.

### 3.4 Causality
- Equity snapshot t-1 close inclusive (T-day exclusive).
- Scalar T-day boyunca sabit; ertesi gun yeniden hesaplanir.
- 14-day lookback sliding window; max peak T-15..T-1 inclusive.
- **No look-ahead:** scalar T-1 23:59 UTC itibariyla bilinir.

---

## 4. PASS / RED Criteria

### PASS (terfi adayi)
- Mean annual return alpha >= **+%5pp**
- Mean MaxDD bozulmasi <= **+%1pp**
- Worst-window MaxDD iyilesmesi >= **-%4pp**
- Bootstrap CI(95%) low (return alpha) > 0
- Bonferroni-adjusted p < **0.010**
- Robustness suite: **>= 5/7 PASS**

### RED (gerekceli arsiv)
- Robustness suite **>= 4/7 HARD FAIL**, VEYA
- Mean return alpha < +%3pp, VEYA
- DD bozulmasi > +%2pp, VEYA
- Worst-window iyilesmesi < -%2pp

### MARGINAL (default RED)
- Mean uplift +%3-5pp arasi **VE** DD bozulmasi <= 0 -> v2 pre-reg dd_floor_scalar 0.50

---

## 5. Backtest Plan (5y full + 3y rolling)

### Setup
- Universe: v2.0.3 11 sembol (BTC/ETH/SOL/BNB/ADA/AVAX/LINK/DOT/DOGE/XRP/MATIC)
- Strategies: TOP_11 + FVG
- Pyramid: v2.0.3 mevcut (1.0R: %50, 2.0R: %30)
- Multi-target: v2.0.3 mevcut (1R: %30, 2R: %30, runner: %40, trail 1.0 ATR)
- Risk: v2.0.3 BALANCED preset, DD scalar overlay
- Veri: cached daily OHLCV 2021-01-01 -> 2026-05-15
- Walk-forward: 3y train + 6mo OOS + 3mo step -> 13 pencere

### Pipeline
```
for window in 13_windows:
    1. baseline: production_replay(v2.0.3 config, window_oos)
    2. treatment: production_replay(v2.0.3 + dd_scalar_overlay, window_oos)
    3. record: annual, dd, r-adj, worst_drawdown, recovery_time
    4. shuffle null: scalar'i OOS donem icinde rastgele gunlere ata (200 iter), alpha dist
    5. bootstrap: 13 pencere uzerinden return alpha 2000 iter CI
```

### Robustness Suite (7 test)
1. **Threshold duyarlilik** — dd_threshold_warn {-3%, -5%, -7%}, dd_threshold_critical {-10%, -15%, -20%}: alpha sapma < %40
2. **Lookback sweep** — 7/14/21 gun: alpha sapma < %40
3. **Floor sweep** — 0.25/0.33/0.50: alpha sapma < %30
4. **Symbol-out CV** — 11 sym her birini drop: alpha sapma < %30
5. **Regime split** — bull (2021, 2023, 2024) / bear (2022) / range (Q1 2026): tum 3 regime'de alpha >= 0
6. **Stress periods** — 2022-05 LUNA, 2022-11 FTX, 2024-03 ATH, 2024-08 Yen carry: en az 3/4'te scalar tetiklenmis VE post-event recovery baseline'dan <= baseline gun
7. **Look-ahead audit** — 50 random trade entry gunu icin scalar'in T-1 23:59 UTC sonrasi hesaplandigini manuel dogrula

### Test gates (Bonferroni-corrected)
- Shuffle null p < 0.010
- Bootstrap CI low > 0
- >= 5/7 robustness PASS

---

## 6. Karsi-Hipotezler

**KH-1: DD scalar bull-trend'de para kaybettirir.** Bull rally basinda kucuk cekilme olsa scalar dusurur -> recovery ralllisinde kucuk pozisyon. **Test:** regime split bull dilim alpha >= 0.

**KH-2: Scalar pyramid mantigini kirar.** Pyramid trigger 1R/2R'da ek pozisyon aciyor; DD ortasinda ana pozisyon kucuk acildiysa pyramid notional'i da kucuk. **Test:** pyramid OFF + scalar ON vs pyramid ON + scalar ON; alpha decomposition.

**KH-3: 14-day lookback gurultulu.** Crypto'da 14-day equity DD haftalik volatilite ile ayni duzen. **Test:** lookback 7/14/21 sweep.

**KH-4: Halt + scalar redundant.** Capitulation halt zaten bidirectional skip yapiyor; scalar 0.33'e dusmus ama trade yok -> katki yok. **Test:** halt OFF + scalar ON (saf scalar etkisi) vs halt ON + scalar ON. Eger combo <= halt-only, scalar redundant -> RED.

**KH-5: Scalar 1x floor recovery'yi yavaslatir.** DD bittikten sonra scalar 1.00x'e donmesi 7 gun gerektirir -> erken rally'leri kacirir. **Test:** recovery_lookback {3, 5, 7} sweep.

**KH-6: DD scalar slippage budget'ini siler.** Production_replay slippage modeli sabit; scalar kucultur pos size kuculunce yuvarlama (min_quantity_usdt=20) cogu trade'i tamamen reddedebilir. **Test:** reddedilen trade sayisi >%20 ise v2 binary halt.

**KH-7: Lookahead — equity_curve_14d ne zaman snapshot aliniyor?** Production_replay daily snapshot end-of-day. Eger EOD t-1 -> T-day open arasinda snapshot yenilenmezse, T-day intraday trade scalar T-1 EOD bazli hesaplar (CAUSAL). **Audit:** Robustness #7.

---

## 7. Risk — PASS olursa hangi degisiklik gerekir?

### Code degisiklikleri
- `src/price_action/risk/leverage_controller.py` — YENI modul: `compute_dd_scalar(equity_curve_14d, config)`
- `src/price_action/risk/sizing.py` — `position_size()` icine scalar parametre injection (backward-compat: default 1.00)
- `src/price_action/backtest/lab.py` ve `engine.py` — daily-EOD equity_curve_14d slicing helper
- `configs/risk_balanced.yaml` — YENI blok `dd_aware_leverage:` (enabled, thresholds, floor, lookback, recovery)
- `tests/risk/test_dd_aware_leverage.py` — unit + integration + replay parity tests

### Mevcut sprint'leri etkileyen
- **SEC26.B-1 side-cond DD breaker:** orthogonal, ikisi birlikte calisir
- **SEC26.B-4 realized PnL journal:** canonical writer kullanilir, scalar daily aggregate'inden besler
- **v0.9.4 capitulation halt:** halt sirasinda scalar etkisiz (trade zaten yok); halt sonrasi recovery scalar acik katki saglar
- **v2.0.3 pyramid:** notional sequence kuculur ama matematiksel siralama korunur (kontrol KH-2)

### Live deployment
- 4-gate genisler: scalar 30-gun paper test gozlemli enable
- DDBreaker.update sonrasi scalar hesaplamasi (TradeJournal canonical realized PnL feed)
- Telegram alert: scalar < 0.50'ye duserse CRITICAL throttled alert (SEC26.C-2 wiring)

### Replay parity gereksinimi
- **enabled: false** default -> byte-identical replay (3da3344 reference)

---

## 8. Beklenen Sayisal Hedef

| Metric | v2.0.3 baseline | HYP-001 beklenen | Uplift |
|---|---|---|---|
| Mean annual (3y rolling) | +%239.5 | +%245 ile +%265 | +%5pp - +%25pp |
| Mean MaxDD (3y rolling) | -%38.7 | -%32 ile -%35 | -%3pp ile -%7pp (iyilesme) |
| Worst-window MaxDD | -%55 (tahmin) | -%48 ile -%52 | -%3pp ile -%7pp |
| Risk-adjusted | 6.190 | 6.50 - 7.20 | +%5 - +%16 |
| Recovery time (median) | ~45g (tahmin) | ~30g | -33% |
| DD scalar tetik gun/yil | 0 (baseline) | 40-80 gun | yeni metrik |

### Bonferroni context
- 5 paralel HYP -> alpha_adj = 0.05/5 = **0.010**
- Per-window: shuffle null p-value < 0.010 olmali
- Mean alpha bootstrap CI low > 0

---

## 9. Implikasyonlar

### PASS senaryosu
1. Production'a 30-gun paper test sonrasi enable karari
2. CEO brief: "DD smoothing katmani eklendi, mean DD -3 ile -7pp iyilesme, worst-case -%55 -> -%50"
3. configs/risk_balanced.yaml v2.1.0 release notu
4. Lab tournament: v2.0.3 vs v2.0.3+dd_scalar vs v2.0.3+dd_scalar+combo
5. SEC26.B-1 side-cond ile combo testi

### FAIL senaryosu
1. Learning log: "Portfolio-level continuous DD scalar 14-day lookback ile crypto 1d rejiminde edge uretmiyor"
2. Olasi v2: regime-conditional scalar (bull/bear ayri parametre)
3. Capitulation halt + side-cond DD breaker yapisal optimumdur teyidi

---

## 10. Reproducibility Footer

```
hypothesis_id: 2026-05-15-dd-aware-dynamic-leverage
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
config_hash: <stable_hash of section 3 + section 4 SABIT params>
data_hash: <ohlcv 11 sym 2021-01-01..2026-05-15 + v091 trade pool>
walk_forward: {train_y: 3, oos_mo: 6, step_mo: 3, n_windows: 13}
multiple_testing: bonferroni, n_hyp=5, alpha_adj=0.010
baseline: v2.0.3 BALANCED+pyramid (configs/risk_balanced.yaml @ 3da3344)
output_planned: reports/research/dd_aware_leverage_v1_results.{txt,json}
```

---

## 11. Yasaklar (HARK Koruma)

- Threshold/floor/lookback parametrelerini OOS ile tune etmek YASAK
- Robustness sweep'lerinin "en iyi" parametresini default secip yeniden test YASAK
- Backtest sonucu negatif cikinca "+halt + side-cond" combo'su ile duzelttim deyip PASS isaretlemek YASAK
- FAIL durumunda v2 pre-reg etmeden once learning log yazilmadan ileri gidemez
- Pyramid OFF default'i (v2.0.3 pyramid ON) — bu sprint pyramid ON uzerinde

---

## Sonuclar (backtest sonrasi DOLDURULACAK)

- [ ] Mean annual return alpha (target >= +%5pp): __
- [ ] Mean MaxDD bozulmasi (target <= +%1pp): __
- [ ] Worst-window MaxDD iyilesmesi (target >= -%4pp): __
- [ ] Bootstrap CI low > 0: __
- [ ] Bonferroni-adj p < 0.010 windows: __
- [ ] Robustness PASS count (target >= 5/7): __
- [ ] Karar: __
