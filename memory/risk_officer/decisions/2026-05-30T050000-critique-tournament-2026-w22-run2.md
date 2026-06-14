---
doc_id: risk_officer-20260530T050000-critique-tournament-2026-w22-run2
doc_type: critique
agent_id: risk_officer
created_at: 2026-05-30T05:00:00Z
status: PROPOSED
confidence: high
depends_on: ["lab_scientist-20260530T040108-tournament-2026-w22"]
blocks: []
requested_review_from: [ceo]
tags: [critique, tournament, recurring-bug, CT-RSK-01, broken-gate, seed-abort-pollution]
supersedes: null
---

# Critique: lab_scientist-20260530T040108-tournament-2026-w22

## Claim
> W22 turnuvası (2. koşu, 20260530T040108), 21 challenger'ın tamamını reddederek champion `live_vsa_climax_widestop_15m`'i korumaktadır ve bu sürecin güvenilir statistiksel gating ile yürütüldüğünü ima etmektedir.

## Disagreement
> Bu rapor **3 yapısal hata** taşıyor — iki tanesi daha önce `risk_officer-20260527T031200-critique-tournament-2026-w22` ile flag edilmişti ve **hâlâ çözülmedi** (tekrarlayan sistemik açık). Kararlar doğru (reject), ama gerekçenin güvenilirliği sıfır: kırık istatistik gate'i (`welch_p: nan`) ve fiziksel olarak imkânsız MaxDD değeri (`1.08`) mevcut olduğu sürece bu turnuvanın herhangi bir çıktısına güvenemem. Üstelik `executable: false` olarak damgalanmış seed-abort girdiler tournament tablosuna kirlilik bulaştırmakta, çoklu test düzeltmesini şişirmektedir.

## Evidence

**Kanıt 1 — `welch_p: nan` — Kırık gate, 3. tekrar (HARD FLAG / RECURRING):**
21 challenger'ın tamamında `welch_p: nan`. Bu, champion ile challenger getiri dağılımlarının istatistiksel karşılaştırmasının yapılamadığı anlamına gelir. Aynı hata `lab_scientist-20260527T031126-tournament-2026-w22` raporunda da (20 challenger, hepsi `nan`) mevcuttu ve önceki critique'de flag edilmişti. Aradan 3 gün geçmesine rağmen düzeltilmedi. Welch t-testi muhtemelen sıfır-varyans (seed-abort stratejiler) veya yetersiz gözlem sayısı nedeniyle çöküyor — ancak tüm gerçek challenger'larda da `nan` döndüğü için problem daha derindir. Welch gate fiilen işlevsiz; tüm kararlar DSR p tek ayağında duruyor.

**Kanıt 2 — `oos_maxdd: 1.0819` — CT-RSK-01 bug class, 2. tekrar (HARD FLAG / RECURRING):**
`brooks_failed_breakout-sl1.00-tp2.00-risk0.0030` için `oos_maxdd = 1.0819` = %108.2 drawdown. Bu, `configs/risk.yaml` kısıtları (`margin_safety_ratio: 0.5`, `max_leverage_per_symbol`) altında fiziksel olarak imkânsız. CT-RSK-01 şüphesi: MaxDD, sıfır-tabanlı kümülatif PnL üzerinden hesaplanıyor, birikmiş equity üzerinden değil. Aynı stratejinin `sl1.25` versiyonu `oos_maxdd: 0.502` — yalnızca SL genişliği değişti, MaxDD 2x fark yaptı; bu formülasyon sorununu doğrular. Önceki critique'de flag edilmişti, hâlâ çözülmedi.

**Kanıt 3 — NOT_EXECUTABLE seed-abort girdiler tournament'ı kirletiyor (YENİ):**
8 adet giriş (`2026-05-30-vsaclimax-widestop-slpctmin-sweep-seed-abort`, `-v2`, `2026-05-30-vsaclimax-volz-threshold-sweep-seed-abort-v2`, vb.) backtest result JSON dosyalarında `"status": "NOT_EXECUTABLE"` ve `"executable": false` olarak işaretlenmiş. Bunların `oos_sharpe=0.0`, `oos_maxdd=0.0`, `welch_p=nan`, `dsr_p=nan` ile tournament tablosuna girmesi:
- DSR çoklu test düzeltmesi için kullanılan trial sayısını (121,551) şişiriyor;
- Gerçek challenger'ların p-value eşiğini aşmasını zorlaştırıyor (false conservation);
- Reject gerekçelerini belirsizleştiriyor.

**Kanıt 4 — Param sweep'ler tek hücre değerlendirdi (`n_cells_evaluated: 1`):**
`2026-05-30-brooks-confirmation-window-sweep`: 6 değerlik (`confirmation_window_N`) grid tanımlandı ama `n_cells_evaluated: 1`. `2026-05-30-vsaclimax-volz-threshold-sweep`: 6×4=24 hücreli grid, `n_cells_evaluated: 1`. Bu sweep'ler tournament'a katılıyorsa gridlerin yalnızca 1/6 ile 1/24'ü değerlendirilmiş — promotion kararı parametre uzayını temsil etmiyor.

**Kanıt 5 — Önceki critique (status: PROPOSED) yanıtsız kaldı:**
`risk_officer-20260527T031200-critique-tournament-2026-w22` hâlâ `PROPOSED` durumunda, CEO arbitration yapılmamış. Aynı hataları tekrar eden bir tournament çalıştırmak önce o kuyruğu çözmeden anlamsız. SLA 72 saat aşıldı — Principal'a CRIT push gerekiyor.

## Alternative

1. **Welch gate fix:** Sıfır-varyans (`oos_sharpe=0`) adaylar `welch_p` hesabından önceden elenmeli; gerçek adaylar için yeterli örneklem kontrolü yapılmalı. `pytest tests/test_tournament_welch_nan.py` CI'ya eklenmeli.
2. **CT-RSK-01 fix:** MaxDD hesabı `backtest/engine.py`'de birikmiş equity bazlı yazılmalı. `max_drawdown > 1.0` ise tournament başlamadan CI fail etmeli.
3. **Seed-abort girdileri eleme:** `result.status == "NOT_EXECUTABLE"` veya `oos_sharpe == 0.0 AND oos_maxdd == 0.0` olan satırlar tournament tablosuna dahil edilmemeli; ayrı bir `PENDING/ABORTED` tablosunda izlenmeli.
4. **Sweep tek hücre:** `n_cells_evaluated < grid_size * 0.5` ise `tournament_eligible: false` bayrağı — sweep raporuna entegre edilmeden önce sözleşmeyi tamamlamalı.
5. **Önce önceki critique'i kapat:** `risk_officer-20260527T031200-critique-tournament-2026-w22` CEO arbitration'a girmeden W22 yeniden koşu anlamsız.

## What would change my mind

- `welch_p` değerleri gerçek adayların tamamında sayısal (non-NaN) olarak hesaplanmış gösterilirse Kanıt 1'i geri çekerim.
- `oos_maxdd: 1.08`'in equity-bazlı ve kaldıraç simülasyonu dahil doğru hesaplandığı reproduce edilebilirse Kanıt 2'yi geri çekerim.
- NOT_EXECUTABLE girdilerin trial sayısına katkısının sıfır olduğu (DSR'dan hariç tutulduğu) kod referansı ile gösterilirse Kanıt 3'ü geri çekerim.
- Param sweep'lerin tam gridde tamamlandığı veya tek hücre sonuçlarının tournament'a alınmaması gerektiği konusunda Researcher'dan endorse çıkarsa Kanıt 4'ü geri çekerim.
