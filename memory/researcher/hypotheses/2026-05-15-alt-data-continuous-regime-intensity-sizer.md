---
hypothesis_id: 2026-05-15-alt-data-continuous-regime-intensity-sizer
date: 2026-05-15
author: researcher_agent (claude-opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1.0
parent_strategy: none (overlay — sizing multiplier from continuous alt-data signal)
parent_baseline: v2.0.3 production champion (3y rolling +%239.5 / DD -%38.7 / r-adj 6.190)
sprint_class: max_roi_2026_05_15 (priority 2/5)
tags: [alt_data, sentiment, funding, open_interest, realized_vol, continuous_sizer, regime_intensity, multi_factor]
backtest_possible: true
data_requirements: [v091 trades, fng_daily.csv, funding_BTCUSDT.csv, open_interest_daily.csv (NEW DEPENDENCY), BTC realized vol computed from OHLCV]
expected_correlation_w_existing: medium-high (mevcut F&G binary skip ile parca ortusur)
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
ceo_brief_ref: max_roi_sprint priority#2 — alt-data continuous; binary F&G'in yerini al
bonferroni_factor: 5
---

# HYP-2026-05-15-002 — Alt-Data Continuous Regime Intensity Index (4-Feature Sizing Multiplier)

## 1. Pre-Registered Iddia (TEK CUMLE)

> v2.0.3 BALANCED+F&G binary fear-skip mantigini (<=20 short skip) birakip, **4 standardize alt-data feature'dan turetilmis continuous Regime Intensity Index (RII in [0, 1])** position size'a multiplicative scalar (0.5x-1.5x mapping) olarak uygulandiginda, v2.0.3 baseline'a karsi **3y rolling 13 pencerede mean annual return >= +%4pp uplift VE DD bozulmasi <= +%2pp** uretir.

### Bagimli Degiskenler
- Mean annual return (3y rolling 13 windows)
- Mean MaxDD
- Worst-window annual + MaxDD
- Risk-adjusted
- Sharpe alpha vs baseline
- Long-tail capture (en iyi %10 trade'lerde sizer scalar dagilimi)
- Bear capture (en kotu %10 trade'lerde sizer dagilimi)

### Bagimsiz Degiskenler (PRE-REGISTERED SABIT)
- **Feature 1:** F&G value 30-day rolling z-score, sign-flipped (high fear -> high RII contribution for **long**)
- **Feature 2:** Funding rate BTCUSDT 24h rolling mean, 30-day z-score (positive funding > 0 = asiri long crowding -> contrarian short bias)
- **Feature 3:** Open Interest BTCUSDT 7-day delta, 60-day z-score (rising OI + falling price = bearish; rising OI + rising price = bullish continuation)
- **Feature 4:** BTC realized volatility 14-day annualized, 90-day percentile rank (high RV percentile = regime danger -> size down)
- **RII formula:** equal-weight Z-aggregation, sigmoid-mapped to [0, 1]:
  ```
  z_sum = (z_fng_sign + z_funding_sign + z_oi_sign + z_rv_sign) / 4
  RII = sigmoid(z_sum)  # in (0, 1)
  ```
- **Sizing scalar mapping:**
  ```
  scalar = 0.5 + 1.0 * RII   # in [0.5, 1.5]
  ```
- Side-aware: long trade icin RII_long, short icin RII_short (sign-flipped features ile)
- baseline = v2.0.3 BALANCED **F&G binary skip kapali** (apples-to-apples)
- walk-forward = 3y train + 6mo OOS + 3mo step -> 13 pencere

### Null Hipotezler (HERHANGI biri PASS olursa hipotez RED)
1. Mean annual return alpha < +%3pp (mean across 13 windows)
2. Mean MaxDD bozulmasi > +%2pp
3. Bootstrap CI(95%) low (return alpha) < 0
4. Robustness 8 testten **>= 4 HARD FAIL**
5. Bonferroni-adj p >= 0.010 (5 paralel HYP)
6. Shuffle null (RII gunleri rastgele permute et) p >= 0.05
7. **Compared to existing F&G binary**: alpha vs F&G-binary-baseline >= +%2pp (yoksa binary daha basit + ayni sonuc, RII overengineering)

---

## 2. Prior Strength — Literatur ve Ic Kanit

### Akademik / Kitap kaynaklari
- **Andrew Ang — "Asset Management" (2014), ch. 7-8:** Multi-factor regime indicators sizing'i risk parity'den daha tutarli; "factor crash protection" continuous signal her zaman binary'den iyi.
- **Robert Engle — "Anticipating Correlations" (2009):** Continuous regime indicators (GARCH-derived RV percentile) crash periyodlarini binary regime switch'lerden daha hassas yakalar.
- **Marcos Lopez de Prado — "Advances in Financial ML" (2018), ch. 17-19:** Continuous regime conditioning monetization edilebilir; binary filtre boundary'de "edge cliff" yaratir.
- **Cliff Asness (AQR) — "Style Investing" (2019):** Continuous style factor exposures regime-aware sizing'le 1.3-1.8x Sharpe artirir.
- **Funding rate as sentiment** — Coin Metrics State of the Network: yuksek perpetual funding asiri leverage proxy'si; mean-reverting on crowded sides (kontrarian short alpha).
- **OI delta as positioning** — Glassnode Q3 2023: OI artisi + fiyat dususu = "leveraged longs liquidation primed"; bearish 5-15 gunluk edge.

### Icsel kanit (proje kanitlari)
- **v0.9.7 BALANCED+F&G (B3 sweep)** — F&G <=20 short skip binary: ROI +%3pp, DD ayni. Bu RII'nin **kanitli baseline'i**.
- **HYP-2026-05-12 funding-oi-divergence** — n=4 trade, OI veri yok funding-only proxy yetersiz, RED. Bu HYP **OI veri eklendigi** senaryoda yeniden degerlendiriyor (data gap fix).
- **Researcher B alt-data agent (v0.9.7 sprint)** — F&G fear-skip karari, alt-data continuous yolun ilk adimi.
- **HYP-2026-05-17 feature space v2 (RED — ML hatti)** — funding_z + fng feature olarak ML'de denendi, RED. Ama o ML filter'di; bu **sizing multiplier**, mekanik tamamen farkli.

### Mevcut sprint'le orthogonality
- F&G binary -> RII'nin **subset'i**. HYP RII continuous + 3 ek feature = strict superset.
- Capitulation halt -> BTC-internal, alt-data degil. ORTHOGONAL.
- DD-aware leverage (HYP-001) -> portfolio equity bazli, sentiment-free. ORTHOGONAL.
- Combo testlenebilir: RII + halt + DD scalar = uc bagimsiz regime katmani.

---

## 3. Mekanik Kurallar (PRE-REGISTERED)

### 3.1 Feature standardization (causal, T-1 EOD inclusive)

```python
def compute_rii_features(fng_series, funding_series, oi_series, btc_close_series, side):
    """
    All series: daily, indexed to UTC midnight, T-DAY EXCLUSIVE (causal).
    Returns: RII in [0, 1].
    """
    # Feature 1: F&G z-score, side-flipped
    fng_t1 = fng_series.iloc[-1]
    fng_mean = fng_series.iloc[-31:-1].mean()
    fng_std = fng_series.iloc[-31:-1].std()
    z_fng = (fng_t1 - fng_mean) / max(fng_std, 1e-6)
    z_fng_sign = -z_fng if side == "long" else +z_fng

    # Feature 2: Funding rate 24h, side-flipped
    fund_t1 = funding_series.iloc[-24:].mean()
    fund_mean = funding_series.iloc[-720:-24].mean()
    fund_std = funding_series.iloc[-720:-24].std()
    z_fund = (fund_t1 - fund_mean) / max(fund_std, 1e-6)
    z_fund_sign = -z_fund if side == "long" else +z_fund

    # Feature 3: OI 7-day delta
    oi_delta_7d = oi_series.iloc[-1] - oi_series.iloc[-8]
    oi_mean = (oi_series.iloc[-61:-1] - oi_series.iloc[-68:-8]).mean()
    oi_std = (oi_series.iloc[-61:-1] - oi_series.iloc[-68:-8]).std()
    z_oi = (oi_delta_7d - oi_mean) / max(oi_std, 1e-6)
    btc_return_7d = (btc_close_series.iloc[-1] / btc_close_series.iloc[-8]) - 1
    if side == "long":
        z_oi_sign = z_oi if btc_return_7d > 0 else -z_oi
    else:
        z_oi_sign = -z_oi if btc_return_7d > 0 else z_oi

    # Feature 4: BTC realized vol 14d annualized, 90d percentile, ALWAYS sign-flipped
    log_rets = np.log(btc_close_series).diff()
    rv_14d = log_rets.iloc[-14:].std() * np.sqrt(365)
    rv_history = log_rets.rolling(14).std().iloc[-90:].dropna() * np.sqrt(365)
    rv_pct = (rv_history < rv_14d).mean()
    z_rv_sign = -2.0 * (rv_pct - 0.5)

    # Aggregate
    z_sum = (z_fng_sign + z_fund_sign + z_oi_sign + z_rv_sign) / 4
    RII = 1.0 / (1.0 + np.exp(-z_sum))
    return RII
```

### 3.2 Scalar Mapping
```python
def rii_size_scalar(RII):
    return 0.5 + 1.0 * RII
```

### 3.3 Sizing Application
```python
final_risk_pct = base_risk_pct * rii_scalar
final_leverage = base_leverage  # UNCHANGED (orthogonal to HYP-001)
```

### 3.4 Missing data fallback
- Herhangi bir feature icin T-1 veri yoksa (NaN), o feature sign value = 0 (neutral); diger features aktif. Tum feature NaN ise RII = 0.50 (neutral, scalar = 1.00x).

### 3.5 Causality audit
- F&G T-1 23:59 UTC value
- Funding rate trailing 24h ending T-1 23:59
- OI snapshot T-1 23:59
- BTC close T-1 23:59
- RII T-day open hesaplanir (T-1 EOD veri ile). T-day intraday degismez.

---

## 4. PASS / RED Criteria

### PASS
- Mean annual return alpha vs **F&G binary baseline** >= **+%2pp**
- Mean annual return alpha vs **v2.0.3 baseline** >= **+%4pp**
- Mean MaxDD bozulmasi <= **+%2pp**
- Bootstrap CI low > 0
- Bonferroni-adj p < **0.010**
- Robustness: **>= 5/8 PASS**

### RED
- Robustness >= 4/8 HARD FAIL
- Alpha vs F&G binary < +%2pp
- Alpha vs v2.0.3 < +%3pp

### MARGINAL
- Alpha +%3-4pp arasi AND DD ayni: ek sprint feature ekleme/cikarma sweep'i

---

## 5. Backtest Plan

### Setup
- Universe / strategies / pyramid / multi-target: v2.0.3 mevcut
- Risk: v2.0.3 BALANCED **F&G binary OFF**
- 3 baseline:
  - **v2.0.3 base** (F&G binary OFF — pure baseline)
  - **v2.0.3 + F&G binary** (mevcut champion)
  - **v2.0.3 + RII** (treatment)
- Veri: ohlcv 11 sym + fng_daily + funding_BTCUSDT + **open_interest_BTCUSDT_daily** (yeni ingest)
- Walk-forward: 3y/6mo/3mo -> 13 pencere

### Pipeline
```
for window in 13_windows:
    1. baseline_pure: production_replay(F&G OFF)
    2. baseline_binary: production_replay(F&G binary)
    3. treatment: production_replay(RII sizing)
    4. record: alpha_vs_pure, alpha_vs_binary, dd_delta, sharpe_alpha
    5. shuffle null: RII gun-permute 200 iter, alpha dist
    6. bootstrap: 13 pencere alpha CI
```

### Robustness Suite (8 test)
1. **Feature ablation 4 -> 3** — her feature drop, retrain RII, alpha kayip < %40
2. **Weight sweep** — 0.25/0.25/0.25/0.25 vs 0.40/0.20/0.20/0.20 (F&G heavy): alpha sapma < %30
3. **Window sweep** — 30d z -> 14d/30d/60d trailing: alpha sapma < %30
4. **Scalar range sweep** — [0.5, 1.5] vs [0.7, 1.3] vs [0.3, 1.7]: alpha sapma < %30
5. **Symbol-out CV** — 11 sym her drop: alpha sapma < %30
6. **Regime split** — bull/bear/range: en az 2'sinde alpha >= 0
7. **Stress test** — 2022-05 LUNA, 2022-11 FTX, 2024-08 Yen carry: RII dusuk (< 0.30), baseline'dan az kayip
8. **Look-ahead audit** — 50 random trade, all 4 feature timestamp T-1 EOD inclusive dogrulamasi

### Test gates
- Shuffle p < 0.010
- Bootstrap CI low > 0
- >= 5/8 robustness PASS
- Vs F&G binary alpha > +%2pp

---

## 6. Karsi-Hipotezler

**KH-1: 4 feature'in 3'u gurultu, sadece F&G katki saglar.** F&G binary alpha = +%3pp (kanitli). RII alpha < binary + 2pp ise diger 3 feature gurultu. Feature ablation testi (Robustness #1) bunu olcer.

**KH-2: OI veri kalitesi yetersiz.** HYP-2026-05-12-funding-oi-divergence RED'di cunku OI veri yoktu. Bu HYP OI veri **DEPENDENCY** kabul ediyor. Data Engineer pipeline gerekiyor (`alt_data_ingest` OI gunluk historical 5y). Eger 5y OI veri yoksa -> HYP **GO-PRE-REQ FAIL**, ingest tamamlanana kadar bekle.

**KH-3: Sigmoid cikisi cok siki (0.45-0.55 dolayinda dolanir).** Z-aggregation small sigmoid'in linear bolgesine sikistirir. RII dagilimi cok dar olursa scalar 0.95-1.05 -> effective no-op. **Test:** RII histogram p25-p75 >= 0.30 spread olmali; eger dar ise z_sum * 2 temperature scaling v2.

**KH-4: Side-flip mekanigi ters calisir.** Long icin fear bullish varsayimi dogrudur ama crypto bear market'te (2022) surekli fear -> tum long'lar buyuk size -> bear amplifies. **Test:** regime split bear dilim alpha >= 0. Aksi halde side-flip sadece short'a uygula (asymmetric).

**KH-5: Lookback (30d, 60d, 90d) kismen overlapping -> feature inter-correlation yuksek.** Diversification ratio low. **Test:** 4 feature'in T-1 oncesi rolling correlation matrix; max |rho| < 0.70 olmali. Yuksek ise PCA-1 tek feature'a indir, v2.

**KH-6: F&G binary deja iyi; RII recovery'yi geciktirir.** F&G <= 20 short skip ani halt (kesin); RII continuous -> deger gradual artar, short hala kucuk size ile acilir -> recovery'de sermaye verimsiz. **Test:** vs F&G binary alpha dogrudan olcer.

**KH-7: Funding rate exchange-specific.** BTCUSDT Binance perpetual funding kullaniliyor; FTX/Bybit/OKX farkli olabilir. Bu sprint Binance-only proxy. v2'de aggregate funding (multi-exchange weighted).

**KH-8: Veri leakage — z-score window son N gun T-day dahil mi?** **Acikca hayir.** Section 3.1'de `iloc[-1]` T-1 EOD, `iloc[-31:-1]` 30 gun trailing T-1 oncesi. Look-ahead audit (Robustness #8) bunu dogrular.

---

## 7. Risk — PASS olursa hangi degisiklik gerekir?

### Code degisiklikleri
- `src/price_action/regime/regime_intensity_index.py` — YENI modul: `compute_rii(features_dict, side)`
- `src/price_action/data/alt_data_loader.py` — OI series loader ekle
- `src/price_action/risk/sizing.py` — `position_size()` icine rii_scalar parametresi (backward-compat default 1.00)
- `scripts/futures_trade_daily.py` — daily RII compute step (T-1 EOD)
- `configs/risk_balanced.yaml` — F&G binary blok deprecated, YENI `regime_intensity_index:` blok
- `tests/regime/test_regime_intensity_index.py` — feature unit + RII integration + look-ahead audit

### Mevcut sprint'leri etkileyen
- **HYP-2026-05-12-funding-oi-divergence (RED, n=4)** — bu HYP onun **revival** ediyor; OI dependency fix sonrasi
- **Researcher B F&G fear-skip** — replace edilir (binary -> continuous)
- **HYP-001 DD-aware leverage** — orthogonal, combo testlenmeli
- **Capitulation halt** — orthogonal, RII bear regime'de dusuk olur ama halt zaten skip'liyor

### Pre-requisite (BLOKLAYICI)
- **OI 5y historical ingestion** — Data Engineer dependency. CoinGlass API veya Coinalyze. Eger 5y veri yoksa HYP test edilemez, 3y veriyle yarim walk-forward (7 pencere, alpha gates orantili azaltilir)

### Live deployment
- 30g paper test: RII histogram dagilimi, daily snapshot tutarliligi
- Telegram alert: RII < 0.30 (extreme bear regime intensity) -> throttled INFO

---

## 8. Beklenen Sayisal Hedef

| Metric | v2.0.3 base | v2.0.3 + F&G binary | v2.0.3 + RII (target) |
|---|---|---|---|
| Mean annual (3y) | +%236 (tahmin pure) | +%239.5 | +%243 - +%252 |
| Mean MaxDD | -%38 (tahmin pure) | -%38.7 | -%36 ile -%40 |
| Alpha vs pure | 0 | +%3pp | +%4 - +%16 |
| Alpha vs binary | -%3pp | 0 | +%2 - +%13 |
| RII tetik gun/yil | - | - | 100-180 gun (scalar < 1.00) |
| Long-tail capture multiplier | 1.00x | 1.00x | 1.30x |

---

## 9. Implikasyonlar

### PASS
1. F&G binary deprecate, RII production'a alinir
2. Multi-factor regime hatti acilir (v2: macro features, BTC.D, total_mcap)
3. Lab tournament: champion vs RII vs combo (RII + DD scalar + halt)
4. CEO brief: "Alt-data continuous regime sizer +%4-13pp uplift, DD ayni"

### FAIL
1. F&G binary lokal optimum; RII overengineering teyidi
2. Learning log: "4-feature continuous RII sigmoid-aggregation crypto 1d edge uretmiyor"
3. Olasi v2: PCA-1 tek synthetic factor; veya feature interaction (RF-based)
4. F&G binary champion korunur

---

## 10. Reproducibility Footer

```
hypothesis_id: 2026-05-15-alt-data-continuous-regime-intensity-sizer
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
config_hash: <stable_hash section 3 + 4 params>
data_hash: <ohlcv 11 sym + fng + funding + OI 5y>
prereq: OI 5y historical ingestion (BLOCKING)
walk_forward: 3y/6mo/3mo n=13 (full data) or n=7 (3y OI fallback)
multiple_testing: bonferroni n=5 alpha_adj=0.010
baseline_pair: (v2.0.3 pure, v2.0.3+F&G binary)
output_planned: reports/research/rii_v1_results.{txt,json}
```

---

## 11. Yasaklar

- Feature ekleme/cikarma OOS sonra (sadece v2 pre-reg ile)
- Sigmoid temperature scaling tune (PRE-REG sabit)
- Multi-exchange funding aggregate (v1 Binance-only)
- RII < 0.50 halt'a cevirme (continuous mantigini koruyalim; binary v2)
- FAIL durumda learning log olmadan v2

---

## Sonuclar (DOLDURULACAK)

- [ ] Mean alpha vs v2.0.3 pure (target >= +%4pp): __
- [ ] Mean alpha vs F&G binary (target >= +%2pp): __
- [ ] Mean MaxDD bozulmasi (target <= +%2pp): __
- [ ] Bootstrap CI low > 0: __
- [ ] Bonferroni p < 0.010: __
- [ ] Robustness PASS (target >= 5/8): __
- [ ] Karar: __
