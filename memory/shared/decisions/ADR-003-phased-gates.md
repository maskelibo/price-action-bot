---
adr: 003
title: Faz Gate'leri Sayısal ve Bağlayıcı
status: accepted
date: 2026-05-08
authors: [human_principal, ceo_agent]
---

# ADR-003 — Faz Gate'leri Sayısal ve Bağlayıcı

## Context

Trading sistemleri "feature creep" ile devasa karmaşıklığa ulaşıp asla canlıya çıkamayabilir. Tersi: yeterince test etmeden canlıya geçip patlayabilir. İkisinin arasında durmak için **disiplinli gate sistemi** gerekli.

## Decision

Her faz sayısal eşiklerle bitiyor; eşik düşerse ileri faza geçilmiyor. Bu eşikler ADR ile değişebilir; ad-hoc esneme yok.

| Faz | Eşik | Değer |
|---|---|---|
| 0 | Veri kalitesi | Eksik mum < %0.1 |
| 1 | Pattern precision | > %75 (manuel etiketli set) |
| 2 | Backtest ROI (3y, all_liquid) | Yıllık net > %70 / Sharpe > 1.5 / MaxDD < %20 / WF dilim %70+ pozitif |
| 3 | Risk sonrası ROI | Sharpe değişimi > -%10 / MaxDD < %15 |
| 4 | ML uplift | OOS Sharpe ML+ > ML- ×1.15 |
| 5 | LLM brief | 1 hafta kesintisiz brief, ≥1 onaylı aksiyon |
| 6 | Paper trading | 4 hafta, P&L sapma < %20 |
| 7 | Mikro canlı | Aylık net pozitif (mikro sermaye) |

## Kritik Kurallar

1. **Gate düşerse Faz N-1'e dön.** "Az fark var, geçirelim" YASAK.
2. **Gate parametreleri değişebilir, ama ADR ile.** Ad-hoc esneme yok.
3. **Gate ölçümleri OOS olmak zorunda.** In-sample sayı geçerli değil.
4. **Çoklu test düzeltmesi zorunlu.** 100 hipotez → Bonferroni / FDR.
5. **Reproducibility manifest zorunlu.** Aynı git_hash + config + data → bit-identical sonuç.

## Alternatives Considered

1. **Esnek gate (%5 sapma kabul).** Reddedildi: insan rasyonelizasyonu kapısı.
2. **Tek bir KPI gate (Sharpe).** Reddedildi: tek metrik manipüle edilebilir.
3. **Yetersiz gate (sadece Sharpe + DD).** Reddedildi: WF dilim consistency olmazsa şans olabilir.

## Consequences

- **Pozitif:** Disiplin. Net karar mekanizması. Hayal kırıklığı önlenir.
- **Negatif:** Bir gate haftalarca/aylarca düşebilir → Faz 1'de geçici tıkanma.
- **Risk:** Çok katı gate uzun süre geçilemezse motivasyon düşebilir → ADR ile gerekçeli ayar mümkün.

## Follow-ups

- Faz 2 gate'i `classic_pa.yaml::gates` olarak somutlaştırıldı.
- Her faz sonunda CEO + Lab consilation oturumu.
