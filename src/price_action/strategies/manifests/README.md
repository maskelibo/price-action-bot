# Strategy Manifests — TF-per-manifest layer

**Status:** Phase 2 complete (SEC-SCALP-S5, 2026-05-17)
**Scope:** 15m TF overrides for all 10 Phoenix-Scalp strategies.
**Next:** 5m manifests (Phase 3); loader integration (Phase 4 ablation sprint).

---

## Manifest Listesi — 15m

| Dosya | Strateji | TF | Version | Kritik Sapma |
|---|---|---|---|---|
| `engulfing_continuation_15m.yaml` | engulfing_continuation | 15m | 1.0.0-15m | pullback_window 10→20, vol_z floor=0.5, primary_R 2.0→1.5 |
| `obv_engulfing_confluence_15m.yaml` | obv_engulfing_confluence | 15m | 1.0.0-15m | obv_lookback 20→96, body_ratio 0.55→0.50, vol_z floor=0.8 |
| `anchored_vwap_reversal_15m.yaml` | anchored_vwap_reversal | 15m | 1.0.0-15m | avwap/poc_lookback 60→96, ema200 DISABLED, rsi genisletildi |
| `brooks_h2_l2_15m.yaml` | brooks_h2_l2 | 15m | 1.0.0-15m | leg_min_bars 3→5, trend_n_bars 10→20, primary_R 2.0→1.5 |
| `pin_bar_round_numbers_15m.yaml` | pin_bar_round_numbers | 15m | 1.0.0-15m | wick_ratio 0.60→0.65, body_ratio_max 0.33→0.30, vol_z=1.0 |
| `equal_highs_sweep_15m.yaml` | equal_highs_sweep | 15m | 1.0.0-15m | lookback 30→48, tolerance 0.15→0.20, reversal_window 3→5, tp 2.5→2.0 |
| `cvd_spike_fade_15m.yaml` | cvd_spike_fade | 15m | 1.0.0-15m | obv_lookback 30→64, zscore_thresh 2.5→3.0, primary_R ayni |
| `vsa_climax_test_15m.yaml` | vsa_climax_test | 15m | 1.0.0-15m | vol_sma_mult 2.5→3.0, wait_max 15→24, tolerance 3%→2%, tp 3.0→2.5 |
| `brooks_failed_breakout_15m.yaml` | brooks_failed_breakout | 15m | 1.0.0-15m | max_bars_to_fail 3→5, sl_atr_factor 0.5→0.7, primary_R 2.0→1.5 |
| `fvg_fill_reversal_15m.yaml` | fvg_fill_reversal | 15m | 1.0.0-15m | min_gap_atr 0.20→0.25, cooldown 5→10, tp_r 2.0→1.5, atr_min 0.005→0.002 |

---

## Planned 5m Manifests (Phase 3)

```
engulfing_continuation_5m.yaml
obv_engulfing_confluence_5m.yaml
anchored_vwap_reversal_5m.yaml
brooks_h2_l2_5m.yaml
pin_bar_round_numbers_5m.yaml
equal_highs_sweep_5m.yaml
cvd_spike_fade_5m.yaml
vsa_climax_test_5m.yaml
brooks_failed_breakout_5m.yaml
fvg_fill_reversal_5m.yaml
```

**Not:** 1m TF KILLED (SEC-SCALP audit). 5m manifests 15m'nin kalibrasyonunu referans alacak; oransal: 1d/288 (1d = 288 × 5m).

---

## Planned Loader API Spec (Phase 4)

```python
# src/price_action/strategies/manifest_loader.py
# (henuz uygulanmadi — Phase 4 strategy class refactor)

def load_manifest(strategy_name: str, timeframe: str) -> StrategyManifest:
    """TF-spesifik manifest yukle; yoksa default manifest doner.

    Arama sirasi:
      1. manifests/<strategy_name>_<timeframe>.yaml
      2. strategy._default_manifest() (inline fallback)

    Args:
        strategy_name: "fvg_fill_reversal", "brooks_h2_l2", vb.
        timeframe: "15m", "5m", "1h", "4h", "1d"

    Returns:
        StrategyManifest (Pydantic model)

    Raises:
        FileNotFoundError: yoksa fallback kullanir (raise etmez)
    """
    ...
```

**Entegrasyon ETA:** Phase 4 ablation sprint (SEC-SCALP S7 planli). Strategy class `__init__` refactor gerekli: `manifest` parametresini `manifest_loader.load_manifest(name, tf)` cagrisiyla doldur.

---

## Kalibrasyon Mantigi — Ortak Prensipler

### Bar bazli sabitler → saat esitleme
| Parametre tipi | 1d ref | 15m orani | 15m deger | Oneri |
|---|---|---|---|---|
| Lookback trend/session | 50 bar | 50 gun | 50 bar = 12.5h | Kabul et (session trend) |
| Lookback uzun trend | 200 bar | 200 gun | 200 bar = 50h | Disable veya ema50 ile degistir |
| Vol z-score window | 60 bar | 60 gun | 60 bar = 15h | 96bar (24h=1gun) |
| Pattern lookback | 20-30 bar | 20-30 gun | 20-30 bar = 5-7.5h | 1-2 seans kabul |
| S/R lookback | 120 bar | 4 ay | 120 bar = 30h | 192bar (48h=2gun) |
| ABC struktur max | 25 bar | 25 gun | 25 bar = 6.25h | 1 seans OK |

### Risk parametreleri
- `primary_R`: 1d=2.0 → 15m=1.5 (fee+slip etkisi daha agir)
- `sl_atr_factor`: Oransal koru; ancak noise icin +0.2 artir
- `vol_z floor`: 1d=0.0 → 15m=0.5-1.0 (noise filtresi zorunlu)

---

## Notlar

- **Loader yok:** Manifestler su an strategy class'i tarafindan OKUNMUYOR. Phase 4'e kadar reference dokumantasyonu olarak tutuluyor.
- **Kod sapmalari:** Bazi parametreler (vol_z_window, vol_sma_period, confirmation_max_wait) manifest'te tanimlanmis ama kodda hardcoded. Phase 4 refactor ile manifest-driven yapilacak.
- **Ablation onceligi:** her manifest'teki "Phase 3 eylem" listesi Phase 4 backtest planini belirler.
