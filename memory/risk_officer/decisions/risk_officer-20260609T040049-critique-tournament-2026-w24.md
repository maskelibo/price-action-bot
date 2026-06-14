---
doc_id: "risk_officer-20260609T040049-critique-tournament-2026-w24"
doc_type: critique
agent_id: risk_officer
created_at: "2026-06-09T04:00:49Z"
status: PROPOSED
confidence: high
depends_on: ["lab_scientist-20260609T040049-tournament-2026-w24"]
blocks: []
requested_review_from: [ceo]
tags: ["critique", "tournament", "statistical_validity", "maxdd_bug", "tail_analysis_missing"]
---

# Critique: lab_scientist-20260609T040049-tournament-2026-w24

CRITIQUE

## Claim
> Lab Scientist, W24 turnuvasında 21 challenger'ın tamamını reddederek champion değişikliği önermedi; tüm kararlar meşru görünüyor.

## Disagreement
> `welch_p: nan` tüm challenger'larda istatistiksel temelsizlik işareti, `oos_maxdd: 1.082` (>%100) hesaplama hatası göstergesi, ve `has_tail_analysis: false` açıkça eksik — bu tournament sonuçları güvenilir değil.

## Evidence

- **Kanıt 1 — welch_p: nan tüm 21 challenger'da:** Welch t-testi'nin NaN dönmesi ya OOS dönemde yetersiz trade (sıfır varyans) ya da kod seviyesinde hesaplama hatası anlamına gelir. Her iki durumda da reject kararları istatistiksel zemine değil, dejenere veri durumuna dayanıyor. "Doğru karar şans eseri" riski var; istatistiksel gate fiilen bypass edilmiş sayılır.

- **Kanıt 2 — oos_maxdd: 1.0819 (>%100) — brooks_failed_breakout-sl1.00:** Fixed-fractional sizing ile %0.30 risk/trade sistemde MaxDD %100'ü geçemez (account sıfırlanır). Bu değer compounding-on-wrong-base (CT-RSK-01 sınıfı), unrealized PnL leak veya backtest engine hesaplama hatasına işaret eder. Bug triage yapılmadan bu rakama güvenilemez.

- **Kanıt 3 — has_tail_analysis: false (deterministic gate tarafından flaglendi):** COVID-2020-03, LUNA-2022-05, FTX-2022-11, Yen Carry-2024-08 crash period'larında test yok. Champion bile bu dönemlerde test edilmemiş; turnuvada sadece OOS Sharpe karşılaştırması yapılmış. Adversary stress-test yokluğu tail-risk körü yapar.

- **Kanıt 4 — Sıfır-trade challenger'lar turnuvaya dahil:** `oos_sharpe: 0.0, oos_maxdd: 0.0, effect_vs_champion: -1.0` → en az 5 challenger OOS dönemde sıfır trade üretmiş. Bu seed-abort / veri yokluğu durumları; reject doğru ama gerekçe "istatistiksel yenilgi" değil "dejenere veri" — karıştırılmamalı.

- **Kanıt 5 — 89,572 total trial, çoklu test enflasyonu:** Bu kadar deneme ile Bonferroni/FDR düzeltmesi açıkça belgelenmemiş. DSR p=1.0 zaten doğal cevap verir ama 89k trial context'inde multiple-testing correction'ın uygulandığı teyit edilmeli.

## Alternative

- **welch_p: nan için:** Her challenger'ın OOS trade count'u loglansın; minimum 30 trade altı "insufficient_data" flag ile ayrı kategoride reject edilsin (istatistiksel reject'ten farklı).
- **MaxDD > %100 için:** `backtest/engine.py` sizing hesaplamasında yanlış-baz triage yapılsın; CT-RSK-01 audit kaydı açılsın. Bu satırın rejection doğru olsa bile engine bug varlığı raporu bozuyor.
- **Tail analysis için:** Turnuvadan bağımsız, Adversary Engineer'a champion (live_vsa_climax_widestop_15m) crash period stress-test görevi verilsin — W25 turnuva öncesi sonuç beklenmeli.
- **Sıfır-trade challengers için:** Turnuva girişi öncesi OOS trade count > 0 pre-filter zorunlu hale getirilsin; "viable challenger pool" ile "degenerate pool" ayrışsın.

## What would change my mind

- `welch_p: nan`'ın beklenen davranış olduğu (örn. "OOS dönem < 30 trade, NaN is documented no-op, reject still valid by DSR alone") dokümante edilirse ve tüm 21 challenger için trade count tablosu sunulursa → bu kritiği supersede ederim.
- `oos_maxdd: 1.082` için "bu R-multiple bazlı ölçüm, %fractional değil" veya "engine PR #X düzeltildi, yeniden hesaplandı" gösterilirse → CT-RSK-01 referansını kaldırırım.
- W25 öncesinde Adversary stress-test raporu gelir ve champion LUNA/FTX dönemlerinde MaxDD < %15 tutarsa → tail analysis eksikliğini kabul edilebilir gecikme olarak revize ederim.

## CEO Arbitrate
Bu critique CEO'nun `arbitrate(lab_scientist-20260609T040049-tournament-2026-w24)` çağrısında değerlendirilir.
SLA: 24 saat (aşılırsa Principal CRIT push).
