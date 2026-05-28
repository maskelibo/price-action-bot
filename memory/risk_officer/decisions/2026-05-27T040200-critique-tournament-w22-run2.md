---
doc_id: risk_officer-20260527T040200-critique-tournament-w22-run2
doc_type: critique
agent_id: risk_officer
created_at: 2026-05-27T04:02:00Z
status: PROPOSED
confidence: high
depends_on: ["lab_scientist-20260527T040116-tournament-2026-w22"]
blocks: []
requested_review_from: [ceo]
tags: [critique, tournament, data-integrity, statistical-process, 2026-W22]
supersedes: null
---

# Critique: lab_scientist-20260527T040116-tournament-2026-w22

## Claim
> W22 tournament 20 challenger'ı test edip tamamını reddederek champion `live_vsa_climax_widestop_15m`'i korumuş ve bu kararın istatistiksel olarak geçerli olduğunu ima etmektedir.

## Disagreement
> `welch_p` tüm 20 challenger için `nan` döndürmüş — birincil istatistiksel karşılaştırma mekanizması tamamen devre dışı; üstelik bir challenger'da `oos_maxdd = 1.08` (%108) hesaplanmış, bu değer `configs/risk.yaml` kısıtları altında aritmetik olarak imkânsız. Kırık istatistiksel altyapı üzerinde kurulan "tüm reject güvenli" sonucu doğrulanamaz.

## Evidence

**1 — welch_p = nan: İstatistiksel motor çökmüş (HARD FLAG)**
Tüm 20 satırda `"welch_p": nan`. Welch t-testi promotion gate'inin birincil kolu —
`dsr_p` tek başına yeterli değil (DSR yalnızca "Sharpe sıfırdan anlamlı mı" sorusunu
yanıtlar, "champion'dan iyi mi" sorusunu değil). `welch_p` NaN iken rejection kararları
istatistiksel kanıta değil, sadece `effect_vs_champion` delta ve DSR p-value'una dayandırılmış
olabilir. Bu gate'in kırık olduğu teyit edilmeden tournament kararına güvenilemez.

**2 — MaxDD > 100%: Backtest engine risk kısıtlarını simüle etmiyor**
`brooks_failed_breakout-sl1.00`: `oos_maxdd = 1.0819` (≈ %108.2).
`configs/risk.yaml` satır 60: `margin_safety_ratio: 0.5`, satır 58: `max_leverage_per_symbol: 5`.
Bu kısıtlar altında likidasyon tetiklenmeden çok önce pozisyon kapanmalı; %108 MaxDD ancak
risk kuralları hiç uygulanmıyorsa ortaya çıkabilir. Aynı stratejinin `sl1.25` versiyonu
`oos_maxdd = 0.502` — yalnızca SL genişliği değiştiyken MaxDD 2.1x fark yaptı. Bu tutarsızlık
hesaplama hatasına işaret ediyor ve **tüm diğer MaxDD figürlerini de güvenilmez kılıyor.**

**3 — 7 challenger sıfır sonuç üretti: Çoklu test havuzu kirletilmiş**
`weekend-gap-fill`, `oi-volume-divergence`, `liquidity-grab-reversal`, `fomc-cpi-event-pre-positioning`,
`daily-scan-shuffle-null`, `btcd-shift-trigger-event`, `cross-strategy-tail-corr-companion-v2` —
hepsinde `oos_sharpe=0.0, oos_maxdd=0.0, dsr_p=nan`. Bunlar backtest üretmemiş, henüz implement
edilmemiş hipotezler. 197.673 trial içinde bu boş slotlar Bonferroni/DSR düzeltme eşiğini
gereksiz yere yükseltiyor; gerçek 13 adayın rejection kararı bu kirlilikten etkilenmiş olabilir.

**4 — anchored_vwap_reversal-sl1.00 rejection gerekçesi belirsiz (Audit Gap)**
OOS Sharpe = 3.51, effect = +1.34 (+134%), DSR p = 0.9986. Yüksek Sharpe ve güçlü effect'e
karşın rejected. Hangi gate tetiklendi? MaxDD = 0.644 champion'ın MaxDD'sini aştı mı?
Bu bilgi raporda yok. Risk Officer olarak rejection gerekçesini audit edemem.

**5 — Champion baseline raporda görünmüyor**
`effect_vs_champion` hesaplandı ama champion'ın kendi OOS Sharpe, MaxDD, Calmar değerleri
tabloda yer almıyor. Karşılaştırma referansını bağımsız olarak doğrulayamıyorum.

**6 — Variant cluster korelasyonu analiz edilmemiş**
3× `anchored_vwap_reversal` (sl1.00/1.25/1.50) + 2× `brooks_failed_breakout` (sl1.00/1.25)
= aynı stratejinin SL varyantları; getirileri yüksek korelasyonlu. Cluster-adjusted DSR
uygulanmadıysa bağımsız 5 trial sayımı geçersiz, çoklu test gücü şişirilmiş.
(`correlation_gate.hard_block_at: 0.9`, configs/risk.yaml satır 82)

## Alternative

- **Fix 1:** `test_welch_p_not_nan()` CI testi — tournament başlamadan istatistiksel motoru assert et; NaN çıkarsa CI fail.
- **Fix 2:** Tournament'a yalnızca `oos_sharpe > 0 AND welch_p IS NOT NULL` koşulunu sağlayan adaylar dahil edilsin; sıfır-sonuçlular `PENDING_BACKTEST` kuyrukta beklesin.
- **Fix 3:** Her `decision: reject` kaydına `reject_reason: list[str]` alanı zorunlu — audit trail için (`["maxdd_gate", "dsr_gate", "effect_gate"]`).
- **Fix 4:** `test_maxdd_cannot_exceed_equity()` — MaxDD > 1.0 çıktığında backtest engine exception fırlatsın.
- **Yeniden çalıştırma:** 4 fix sonrası W22 tournament'ı 13 gerçek adayla yeniden çalıştır.

## What would change my mind

- `welch_p = nan` sebebi "N < 30 — yeterli trade yok" gibi kasıtlı ve log'da belgelenmiş bir sınırsa → Kanıt 1'i geri çekerim (ancak raporda açıkça işaretlenmeli).
- `brooks_failed_breakout-sl1.00` MaxDD 1.08'inin kaldıraçlı likidasyon simülasyonu dahil doğru hesaplandığı ve `sl1.25` ile 2.1x farkın SL geometrisinden kaynaklandığı matematiksel olarak gösterilirse → Kanıt 2'yi geri çekerim.
- 7 sıfır-sonuçlu hipotezin DSR hesabından zaten hariç tutulduğu ve `total_trials=197.673` sadece gerçek adaylar üzerinden hesaplandığı gösterilirse → Kanıt 3'ü geri çekerim.

## CEO Arbitrate
Bu critique CEO'nun `arbitrate(lab_scientist-20260527T040116-tournament-2026-w22)` çağrısında
değerlendirilir. SLA: 24 saat (aşılırsa Principal CRIT push).
