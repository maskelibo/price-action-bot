---
adr_id: ADR-007
title: Volatility-Targeted Sizing — Opsiyonel Kayıp Koruma Katmanı
status: accepted
date: 2026-05-09
author: ceo
tags: [risk, sizing, vol_target, dd_protection, optional]
---

# ADR-007 — Volatility-Targeted Sizing

## Bağlam

Production aday Engulfing R%2 lev 1-5x dinamik konfigi yıllık +%68-81 üretiyor ama yıllar arası volatilite çok yüksek (σ %60: Y1 +%68, Y2 +%10, Y3 +%156). Kullanıcı "DD biraz fazla değil mi, kaybetmeden kazanmak mümkün değil mi" diye sorguladı.

3 farklı kayıp koruma tekniği test edildi:
1. **Volatility-targeted sizing** — sakin günde büyük, riskli günde küçük pozisyon
2. **Equity stop-out** — %20 kayıpta tüm ay durdur
3. **Partial close at 1R** — yarı kazanç koru

## Karar

**Vol-targeted sizing kalıcı opsiyonel modul olarak eklendi** (`src/price_action/risk/vol_target.py`).

### Neden vol-target?

Test sonuçları (3y backtest):

| Konfig | Yıllık | DD | σ (yıllar arası) |
|---|---:|---:|---:|
| Baseline R%1 | +%36 | -%38 | %35 |
| **+ Vol-target** | +%32 | -%37 | **%21** ⭐ |
| + Equity stop-out | +%41 | -%38 | %35 |
| + Partial close | +%11 (kötü) | -%38 | %29 |

**Vol-target en iyi tutarlılık**: σ %35 → %21 (1.7x iyileşme), 3 yıl da pozitif (+%18, +%21, +%63), getiri kabul edilebilir düşüş (%36 → %32).

### Formül

```
factor = target_atr_pct / current_atr_pct
factor = clamp(factor, min_factor, max_factor)
final_risk_dollars = base_risk * factor
```

Örnekler:
- ATR %4 (target) → factor 1.0, normal pozisyon
- ATR %8 (high vol) → factor 0.5, yarı pozisyon
- ATR %2 (low vol) → factor 1.5 (clamped), %50 büyük pozisyon

### Konfig (`risk.yaml`)

```yaml
vol_target:
  enabled: false                    # default kapalı
  target_atr_pct: 0.04              # %4 günlük ATR hedef
  min_factor: 0.20                  # extreme high-vol koruma
  max_factor: 1.50                  # extreme low-vol fırsat
```

## Sonuç

- ✅ Kalıcı modul (`vol_target.py`), 15 test, default kapalı
- ✅ Kullanıcı `enabled: true` ile aktif edebilir
- ✅ Production konfig (engulfing R%2 lev 1-5x) DEĞİŞMEDİ — vol-target ekstra opsiyon
- ⚠️ Aktif edilirse paper trading orchestrator'ın da `vol_target_factor` hesabını uygulaması gerekir (paper_trading_loop.py'da entegrasyon bekliyor)

## Alternatifler (red edilen)

1. **Production'a default ON yap** → red: getiri %4 düşer, kullanıcı seçim yapsın
2. **Equity stop-out kalıcı** → red: σ aynı kalıyor, vol-target kadar tutarlılık iyileştirmesi yok
3. **Partial close** → red: sistemi bozuyor (yıllık %36 → %11)

## Referans

- `src/price_action/risk/vol_target.py` — module
- `tests/test_vol_target.py` — 15 test
- `scripts/safe_dd_techniques.py` — sweep
- `configs/risk.yaml` — config
