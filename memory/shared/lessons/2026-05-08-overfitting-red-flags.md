---
type: lesson
date: 2026-05-08
authored_by: human_principal
applies_to: [researcher, lab_scientist, ceo]
confidence: high
tags: [overfitting, methodology, anti-pattern]
---

# Overfitting Kırmızı Bayrakları

## Ders

Bir backtest "çok iyi" sonuç verdiğinde sevinmek yerine şüphe et. Aşağıdaki bayraklardan herhangi biri varsa **stratejiyi reddet** — gate'i geçse bile.

## Bayraklar

1. **In-sample / Out-of-sample Sharpe farkı > %50.**
   IS Sharpe 3.0, OOS Sharpe 1.2 ise → overfit. OOS Sharpe gerçek performansa daha yakın.

2. **Best parameters parametre uzayının sınırında.**
   `atr_multiplier ∈ [1.5, 3.5]` aralığında best 3.5 ise → daha geniş aralık dene; muhtemelen optimum tablonun dışında, yani kalıp asıl değerini kanıtlamadı.

3. **Çok ince parametre uzayı.**
   `atr_multiplier` `0.01` adım ile optimize ediliyor → over-fit. `0.25` adım yeterli.

4. **Trade sayısı düşük.**
   N < 100 trade varsa istatistik anlamsız. Daha çok sembol veya daha uzun dönem.

5. **Tek bir periyot/sembol baskın katkı.**
   Toplam P&L'in %80'i 2022 Mart'ından geliyorsa → muhtemelen LUNA çöküşünden short edge yakalandı, tekrar etmez.

6. **Walk-forward dilimleri arası varyans yüksek.**
   12 dilimden 4'ü pozitif, 8'i negatif → gerçek edge yok, IS şans.

7. **Bonferroni / FDR sonrası anlamlılık kaybediliyor.**
   100 trial × 0.05 → en az 5 false positive bekle. Düzeltme uygulanmazsa "best Sharpe" şans.

8. **Strateji "çok mantıklı bir hikâye" anlatıyor ama sayı zayıf.**
   Hikâye seni bias'lar — sayı kazanır.

## Pratik Kural

> Overfit şüphesi varsa, parametre uzayını daralt ve yeniden test et. Sonuç hâlâ tutarlıysa OK; düşüyorsa overfit.

## Yakalanma

`backtest/walk_forward.py::robustness_suite()` her aday için yukarıdaki bayrakların kontrolünü otomatik yapar; yakalanan red sebebi loglanır.
