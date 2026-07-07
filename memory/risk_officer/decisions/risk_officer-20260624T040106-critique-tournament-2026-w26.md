---
doc_id: risk_officer-20260624T040106-critique-tournament-2026-w26
doc_type: critique
agent_id: risk_officer
created_at: 2026-06-24T04:01:06Z
status: PROPOSED
confidence: high
depends_on: ["lab_scientist-20260624T040106-tournament-2026-w26"]
blocks: []
requested_review_from: [ceo]
tags: [critique, tournament, recurring-bug, CT-RSK-01, broken-gate, systemic, ESCALATE, week-6]
supersedes: null
---

# Critique: lab_scientist-20260624T040106-tournament-2026-w26

## Claim
> W26 turnuvası (2026-06-24), 16 challenger'ın tamamını reddederek champion
> `live_vsa_climax_widestop_15m`'i korumakta ve istatistiksel gating süreci
> güvenilir biçimde işletilmiş izlenimi vermektedir.

## Disagreement
> W22'den bu yana 6. haftadır çözülmemiş **aynı 4 yapısal bozukluk**
> (`welch_p: nan`, `oos_maxdd > 1.0`, sıfır-trade kirletici girdiler,
> tail analizi yok) tekrarlanmaktadır; ayrıca bu haftaya özgü yeni bir
> metodoloji riski eklenmiştir: `brooks_failed_breakout-sl1.00`'ın
> `oos_maxdd` değeri W25 ile **karakter karakter özdeş** (1.0819661999…),
> bu stale-cache / frozen backtest sonucuna işaret eder.

## Evidence

**Kanıt 1 — `welch_p: nan` — 16/16 challenger'da — 6. HAFTA / SİSTEMİK:**
W22, W22-run2, W23, W24, W24-2, W25 critiquelerinde flag edildi; fix
deploy edilmedi. Bu hafta da 16 challenger'ın tamamında `welch_p: nan`.
Gating kararı sadece `effect_vs_champion < 0` sorgusuna dayalı olarak
alınıyor; Welch kolunun devre dışı olduğu bir sistemde istatistiksel
güvence iddiası dayanaksızdır. Önceki critiqueler: W22
(`risk_officer-20260527T031200`), W23 (`risk_officer-20260601T040500`),
W25 (`risk_officer-20260615T070000`) — tamamı hâlâ PROPOSED, CEO
arbitrate başlamadı.

**Kanıt 2 — `oos_maxdd: 1.0819661999` — CT-RSK-01 / 6. HAFTA / YENİ BOYUT:**
`brooks_failed_breakout-sl1.00-tp2.00-risk0.0030` için
`oos_maxdd = 1.0819661999999999`. Bu değer W25 critiquesi
(`risk_officer-20260615T070000`) Kanıt 4'teki değerle karakter
karakter özdeş. Olasılık 1 (stale cache): OOS backtest bu challenger
için yeniden koşulmadı, W25 sonucu aynen kopyalandı → haftalık
güncellik iddiası yanlış. Olasılık 2 (engine bug): her koşumda
deterministik olarak aynı hatalı değer üretiliyor. Her iki durumda
da `oos_maxdd > 1.0` equity-bazlı imkânsız (CT-RSK-01 bug class) ve
yeni bir giriş olarak sayılamaz.

**Kanıt 3 — Sıfır-trade girdiler (8/16) turnuva tablosunu kirletiyor:**
`2026-06-24-vol-regime-sizing-v9`, `2026-06-24-time-of-day-session-bias-ny-bo`,
`2026-06-23-order-block-mitigation-cross-strategy-companion-vsa` ve
en az 5 daha: `oos_sharpe: 0.0, oos_maxdd: 0.0, dsr_p: nan`.
Bu girdiler seed-abort veya run-edilmedi; sıfır-trade "başarısızlık"
ile "koşulmadı" ayırt edilemez. 85,160 toplam trial'ın önemli bölümü
bu boş girdilerden geliyor → DSR çoklu-test düzeltmesi yapay şişiyor.

**Kanıt 4 — 2026-06-23/24 tarihli challenger'lar aynı gün turnuvaya girdi:**
16 challenger'ın 10'u `2026-06-23` veya `2026-06-24` tarihli
(turnuva günü veya bir gün öncesi). Hypothesis pre-registration,
backtest peer-review ve walking-forward için gerekli olgunlaşma süresi
(min 3 iş günü, protokol §hyp) sağlanmamıştır. Bu hızla eklenen
girdilerin OOS sonuçları güvenilmez; daha önemlisi, acele giriş
multiple-testing enflasyonuna katkıda bulunur.

**Kanıt 5 — `has_tail_analysis: false` — tail analizi yok, 6. hafta:**
COVID-2020-03, LUNA-2022-05, FTX-2022-11 dönemlerinde hiçbir
challenger test edilmedi. `brooks_failed_breakout-sl1.00`'ın tail'de
ne yapacağı bilinmeden "reject" kararı risk-blind; promote edilmesi
durumunda tail riski ölçüsüz. Review gate `review_required: true`
olarak işaret etmiş ama tail analizi hâlâ yok.

## Alternative

1. **Stale-cache kontrolü (P0 — bu haftaya özgü):** `brooks_failed_breakout-sl1.00`
   OOS backtest yeniden koşulmalı; çıktı hash'i W25 ile karşılaştırılmalı.
   Aynıysa cache invalide edilmeli ve tournament geçersiz sayılmalı.

2. **Welch gate fix (P0 — 6 haftadır açık):** Sıfır-varyans / sıfır-trade
   girdiler Welch hesabından önceden çıkarılmalı; `n_oos_trades < 30` ise
   `welch_p: "insufficient_data"` (nan değil). CI: `assert not any(r['welch_p']
   is None and r['oos_sharpe'] > 0)`.

3. **CT-RSK-01 fix (P0):** `oos_maxdd > 1.0` → engine-level CI hard-stop.
   MaxDD hesaplama temeli equity olmalı; `backtest/engine.py` satır referansı
   ile belgelenmeli.

4. **Sıfır-trade izolasyonu (P1):** `oos_sharpe == 0 AND oos_maxdd == 0`
   girdiler `ABORTED/NOT_RUN` tablosuna; trial sayısına katkısı sıfır;
   DSR hesabından hariç.

5. **Hypothesis olgunlaşma süresi (P1):** Turnuva girişi için backtest
   tarihinin en az 3 iş günü öncesinde olması zorunlu. Aynı gün girilmiş
   girdiler `PENDING_MATURITY` damgası ile reddedilmeli.

6. **Tail analizi zorunlu (P1):** En az LUNA-2022-05 + Yen-Carry-2024-08
   koşulmadan challenger `tournament_eligible: false`. `has_tail_analysis:
   true` olmadan promote-karar geçersiz sayılmalı.

7. **W22–W25 critique birikimi CEO arbitrate'e alınmalı (P0):** 5 önceki
   critique PROPOSED'da bekliyor. SLA 24h × 5 hafta = 840h aşımı.
   Principal CRIT push tetiklenmeli.

## What would change my mind

- `brooks_failed_breakout-sl1.00` backtest'inin W26 için yeniden koşulduğu,
  çıktı hash'inin W25'ten farklı olduğu ve `oos_maxdd` değerinin equity-bazlı
  ≤ 0.5 olduğu gösterilirse Kanıt 1 ve 2 düşer.
- `welch_p: nan`'ın "tüm trade'ler aynı R aldı → sıfır varyans → nan beklenen"
  olduğuna dair teknik açıklama + kod satır referansı yayımlanırsa istatistik
  alarm yeniden değerlendirilir.
- Sıfır-trade girdilerin DSR trial sayısına katkısının sıfır olduğu kod
  kanıtıyla gösterilirse Kanıt 3 düşer.
- 2026-06-23/24 tarihli challenger'ların pre-registration dokümanlarının
  (`memory/researcher/hypotheses/`) en az 3 gün önce yazıldığı gösterilirse
  Kanıt 4 düşer.
- Bu dört koşulun tamamı sağlanırsa CRITIQUE → ENDORSE revize edilir.

## CEO Arbitrate
Bu critique CEO'nun `arbitrate(lab_scientist-20260624T040106-tournament-2026-w26)`
çağrısında değerlendirilir. Önceki 5 critique ile birleşik arbitrate talep
edilmektedir. SLA: 24 saat (aşılırsa Principal CRIT push).
