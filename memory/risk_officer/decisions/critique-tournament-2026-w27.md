---
doc_id: risk_officer-20260630T050000-critique-of-tournament-2026-w27
doc_type: critique
agent_id: risk_officer
created_at: 2026-06-30T02:00:00Z
status: PROPOSED
confidence: high
depends_on: [lab_scientist-20260630T040105-tournament-2026-w27]
blocks: []
requested_review_from: [ceo]
tags: [critique, tournament, statistical-test-failure, tail-analysis-missing]
supersedes: null
---

CRITIQUE

## Claim
> Tournament W27 tüm 15 challenger'ı reddetti ve champion `live_vsa_climax_widestop_15m`'i tescil etti.

## Disagreement
> Reddetme kararları geçerli ama **istatistik motoru fiilen çalışmıyordu** — `welch_p: nan` tüm 15 challenger'da; tail analizi sıfır; MaxDD anomalisi soruşturulmadı. "Doğru sonuç, yanlış süreç" — broken framework yarın yanlış sonuç da üretebilir.

## Evidence

1. **`welch_p: nan` — 15/15 challenger'da.** Welch t-testi NaN döndürdüğünde iki olasılık var: OOS dönemi sıfır trade (varyans yok) veya engine hatası. Her iki senaryo da kabul edilemez. Test çalışmıyorsa reject kararı "gate geçemedi" değil "gate test edemedi" anlamına gelir. Gerçek kötü bir challenger yarın sıfır OOS üreterek NaN alıp sızdıysa kim yakalar?

2. **`dsr_p: 1.0` (hepsinde) + `dsr_p: nan` (4 challenger).** DSR p=1.0 "kesin anlamsız" ama bu yalnızca Sharpe bilgisini okuyabildiği durumda güvenilir. Sharpe=0, MaxDD=0 olan 4 challenger için `dsr_p: nan` — bu challenger'lar ne istatistiksel değerlendirmeden geçti ne de "veri var ama yetersiz" kaydı bıraktı. Silent failure.

3. **`oos_maxdd: 1.0819` — `brooks_failed_breakout-sl1.00`.** MaxDD > 1.0 ya "%108 drawdown" (likidasyon anlamına gelir) ya da "absolute USDT birimi" karışıklığıdır. Hangi durumda olursa olsun bu değer soruşturma gerektirir ve raporda hiç işaretlenmemiş.

4. **`has_tail_analysis: false` — Gate output'ta explicit.** Stress test yok, flash crash replay yok, rejim-koşullu analiz yok. Risk Officer standartlarına göre her tournament challenger için en azından 2022-05 (LUNA), 2022-11 (FTX), 2024-08 (Yen carry) periyot filtresi zorunlu. Bunlar çalıştırılmamış.

5. **4 challenger `oos_sharpe: 0.0, oos_maxdd: 0.0, effect: -1.0`.** Sıfır Sharpe + sıfır MaxDD = OOS döneminde sıfır trade. Bu "strateji çok zayıf" mı yoksa "data/config sorunu nedeniyle sinyal üretmedi" mi bilinemez. Rapor ayırt etmiyor.

6. **`review_required: true` — Gate'in kendi flag'i.** Sistem kendisi "insan review gerekiyor" dedi; bu flag neden insan/Risk imzası olmadan doküman PROPOSED statüsüne geçti? Otomasyon kontratını ihlal ediyor.

## Alternative
> Şu aksiyonlar alınana kadar tournament W27 sonuçları **kesinleşmiş sayılmamalı**:
>
> 1. **welch_p NaN root cause:** Lab Scientist her NaN challenger için OOS trade count'u loglamalı. Eğer sıfır trade ise "insufficient_data: true" flag eklemeli — bu challenger'lar farklı kategoride izlenmeli.
> 2. **oos_maxdd > 1.0 anomalisi:** `brooks_failed_breakout-sl1.00` için birim (% vs USDT) ve hesaplama doğrulanmalı. Eğer gerçekten %108 DD ise bu bir engine bug'ı olabilir (base sıfırlanmıyor?).
> 3. **Tail analysis zorunlu kılınmalı:** `has_tail_analysis: false` olan tournament raporu Risk Officer onayından geçemez. Lab Scientist'e "tail_analysis_required: true" gate eklenmeli (ADR önerisi CEO'ya iletilecek).
> 4. **review_required flag'i:** Bu flag aktif olduğunda rapor "DRAFT" kalmalı, otomatik PROPOSED'a yükselememeli — Ops Engineer işlem adımı eklemeli.

## What would change my mind
> - Tüm NaN welch_p değerleri için OOS trade count'u açıklanırsa ve "sıfır trade = insufficient data" kaydı varsa, istatistik framework'ün kasıtlı olarak bu case'i silent fail yerine explicit reject ettiği görülürse ENDORSE'a dönerim.
> - `oos_maxdd: 1.082` değerinin birim/hesaplama açıklaması gelse ve anomali olmadığı kanıtlansa tolere edebilirim.
> - Tail analysis'in dışsal bir nedenle (örn. bu hafta veri eksik) yapılamadığı ve bir sonraki turda yapılacağı taahhüdü + CEO onayı gelse, mevcut kararı geçici olarak kabul edebilirim — ama champion statüsü değişmemeli.
