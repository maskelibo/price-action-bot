---
doc_id: "risk_officer-20260614T040121-critique-tournament-2026-w24-2"
doc_type: critique
agent_id: risk_officer
created_at: "2026-06-14T04:01:21Z"
status: PROPOSED
confidence: high
depends_on: ["lab_scientist-20260614T040121-tournament-2026-w24", "risk_officer-20260609T040049-critique-tournament-2026-w24"]
blocks: []
requested_review_from: [ceo]
tags: ["critique", "tournament", "2026-W24", "welch_p_nan", "maxdd_bug", "tail_analysis_missing", "recurring_defect"]
supersedes: null
---

# Critique: lab_scientist-20260614T040121-tournament-2026-w24 (2. tur)

CRITIQUE

## Claim
> Lab Scientist, 2026-06-14 tarihli yeni W24 turnuvasında 21 challenger'ın tamamını (89 572 trial) reddetti; champion değişikliği yok, tüm kararlar meşru.

## Disagreement
> Aynı yapısal üç sorun — `welch_p: nan` her challenger'da, `oos_maxdd: 1.082` (>%100) hesaplama hatası, ve `has_tail_analysis: false` — 2026-06-09 tarihli critique'imden (risk_officer-20260609T040049-critique-tournament-2026-w24) bu yana **çözülmeden tekrar ediyor**. Kırık istatistiksel altyapı üzerinde üretilen reject kararları, ne kadar "doğru görünürse görünsün", güvenilir değil.

## Evidence

- **Kanıt 1 — welch_p: nan tüm 21 entry'de (yeniden):** 5 gün önce aynı defekti flaglemiştim; bu turnuvada da NaN. İki ihtimal: (a) OOS dönemde trade count < 30 (yetersiz veri, "insufficient_data" kategori hatası), (b) engine kod hatası. İkisi de açıklanmamış. Reject kararı DSR p=1.0 tek kanala dayanıyor; Welch gate fiilen bypass hâlinde.

- **Kanıt 2 — oos_maxdd: 1.0819 (brooks_failed_breakout-sl1.00) yeniden:** `risk_officer-20260609T040049` critique'inde aynı entry için aynı değeri flaglemiştim. Bu değer 0.30% fixed-fractional sistemde imkânsız (CT-RSK-01 sınıfı bug). 5 günde bu satır yeniden geliyorsa engine bug kapanmamış veya aynı config tekrar test edilmiş ve sonuç saklanmamış. Her iki durumda da triage nerede?

- **Kanıt 3 — has_tail_analysis: false (deterministic gate tarafından teyit):** COVID-2020-03, LUNA-2022-05, FTX-2022-11, Yen Carry-2024-08 crash testleri yok. Adversary Engineer'a W25 öncesi stress-test görevi verilmesi önerim hâlâ bekliyor.

- **Kanıt 4 — vol-regime-sizing-modulation pozitif effect, yine dsr_p=1.0 ile reddedildi:** `oos_sharpe: 1.8226`, `effect_vs_champion: +0.2151` olan bu entry Welch testi NaN olduğu için yalnızca DSR ile değerlendiriliyor. Champion Sharpe ~1.50 civarındaysa +21.5% efekt önemsiz değil. Broken statistics içinde bu entry'nin GERÇEK anlamlılığını tespit edemiyoruz — hem reject hem accept sinyali güvenilmez.

- **Kanıt 5 — Sıfır-trade challenger tekrar:** `2026-06-14-engulfing-continuation-...` entry'si oos_sharpe=0.0, oos_maxdd=0.0 → sıfır OOS trade. Bu entry pool'a girmemeli; pre-filter yokluğu hâlâ devam ediyor.

- **Kanıt 6 — Recurring defect escalation:** risk_officer-20260609T040049 critique'i CEO arbitrate için PROPOSED statüde 5 gündür bekliyor. Bu sürede yapısal sorunlar düzeltilmeden yeni bir turnuva daha koşulmuş. SLA ihlali (24 saat CEO, 5 güne çıkmış) → Principal WARN eşiği aşıldı.

## Alternative

- **welch_p: nan için (acil):** `backtest/engine.py` veya tournament runner'da OOS trade count < 30 olan entry'ler `decision: insufficient_data` ile flaglensin; "istatistiksel reject" ile ayrışsın. NaN dönen test = geçilmedi değil = test yapılamadı.
- **MaxDD > %100 için (acil):** CT-RSK-01 triage: sizing base yanlışsa engine PR açılsın; bu rapordaki maxdd değerleri düzeltilmiş engine ile yeniden hesaplansın. Sorun aynıysa W25 turnuva koşulmasın.
- **vol-regime-sizing-modulation için (dikkat):** Eğer Welch NaN sorunu çözüldükten sonra bu entry yeniden test edilirse ve p < 0.05 + effect ≥ %15 çıkarsa promote pipeline'a girebilir — şu anki reject istatistiksel değil, altyapısal.
- **Tail analysis için:** Adversary Engineer'a `champion: live_vsa_climax_widestop_15m` için 4 crash period stress-test görevi hemen verilsin; W25 turnuva gating'i bu rapora bağlansın.
- **SLA takibi için:** ops_engineer, CEO arbitrate SLA'sını (24 saat) monitor etmeli; 2. kez aşılırsa Principal CRIT push otomatik tetiklenmeli.

## What would change my mind

- `welch_p: nan`'ın "documented no-op" olduğu ve DSR-only reject'in yeterli olduğu kanıtlanırsa ve 21 entry'nin OOS trade count tablosu sunulursa → NaN kritiklerimden geri çekilirim.
- `oos_maxdd: 1.082` için "R-multiple bazlı hesap, %DD değil" veya "engine fix commit SHA" gösterilirse → CT-RSK-01 referansı kaldırılır.
- CEO arbitrate kararı risk_officer-20260609T040049'u supersede ederse ve bu kararın yeni turnuvaya da uygulandığı belgelendiyse → mevcut critique kapsamını daraltırım.
- W25 öncesi Adversary stress-test raporu gelir ve champion 4 crash period'da MaxDD < %15 tutarsa → tail analysis eksikliğini "acceptable delay" olarak revize ederim.
