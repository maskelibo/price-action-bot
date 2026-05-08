---
type: lesson
date: 2026-05-08
authored_by: human_principal
applies_to: [researcher, signal_chief, lab_scientist]
confidence: high
tags: [lookahead, methodology, anti-pattern]
---

# Lookahead Bias — Sıfır Tolerans

## Ders

Backtest'te lookahead bias en yaygın ve en sinsi hatadır. Tek bir `df.shift(-1)` veya `rolling().center=True` veya bar kapanışından önce karar — sonuçları gerçek dışı ölçüde iyimser yapar. Üretilen tüm pattern detector'lar şu testleri geçmek ZORUNDA:

1. **Causality test:** `detector(df.iloc[:t+1])[t]` her zaman `detector(df)[t]` ile aynı olmalı.
2. **Bar timing:** Karar `t` mumunun close'una bağlıysa, giriş `t+1` mumunun open'ında olur. Asla `t` mumunda hem karar hem giriş.
3. **Indicator alignment:** `rolling().mean()` ve benzerleri `min_periods` parametresi düzgün ayarlanmazsa NaN sızabilir veya gelecek bilgisi alabilir — testler her ikisi için.

## Pratik Kural

> Şüphe yaratan her satır için 2 dakika ekstra testle.

## Yakalanma Yolları

- Aynı indicator'i hem detector hem rapor için kullanırken farklı window davranışı.
- Veri ön-işlemde "smoothing" (örn. SMA centered).
- Outlier "düzeltme" — outlier düzeltmesi t bilgisi bulaşması.
- Backtest'in fee/slippage parametresini optimize etmek (out-of-sample'a sızma).

## Düzeltme

`tests/test_lookahead.py` her CI'da çalışır; başarısız test → CI red. Yeni detector eklerken bu test güncellenir.
