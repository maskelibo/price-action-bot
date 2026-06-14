---
doc_id: risk_officer-20260603T040203-endorse-stress-futures15m-crit-v5
doc_type: endorse
agent_id: risk_officer
created_at: 2026-06-03T04:02:03Z
status: PROPOSED
confidence: high
depends_on: ["adversary_engineer-20260603T040203-stress-2026-06-03-futures15m"]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures15m, crit, v5, backtest-motor-corrupt, compounding-inflation, covid-blind-spot, systemic, principal_escalation, paper_halt_mandatory]
supersedes: risk_officer-20260530T054106-endorse-stress-futures15m-crit-v4
---

# ENDORSE — adversary_engineer-20260603T040203-stress-2026-06-03-futures15m

> **⚠️ BEŞİNCİ ENDORSE — PAPER HALT ARTIK TAVSİYE DEĞİL, ZORUNLULUK.**
> Öncekiler:
> - v1: `risk_officer-20260529T004106-endorse-stress-futures15m-crit` — pool empty, config missing
> - v2: `risk_officer-20260529T014200-endorse-stress-futures15m-crit-rerun` — same
> - v3: `risk_officer-20260530T024515-endorse-stress-futures15m-crit-v3` — same
> - v4: `risk_officer-20260530T054106-endorse-stress-futures15m-crit-v4` — **paper halt ÖNERİLDİ**, aktif_state'e göre bot hâlâ çalışıyor (2g+ uptime)
>
> V4'teki paper halt önerisi dikkate alınmadı. V5 artık öneri değil: **hard veto gerekçesi.**

ENDORSE

## Claim

> `futures15m` botu beş tarihsel kriz penceresinde başarısız oldu (0/5); bu başarısızlık yalnızca DD gate ihlalinden ibaret olup, ölçülebilir tail riski nedeniyle CRIT statüsündedir.

## Why I Endorse

Adversary Engineer'ın bu turda getirdiği yeni analiz katmanı önceki dört CRIT'ten niteliksel olarak farklıdır. Önceki dört çalıştırmada sorun "veri yoktu, göremiyorduk" idi. Bu turda sorun "veri var ama sayılar gerçekçi değil" — bu, **backtest motorunun kendisinin bozuk olduğu** anlamına gelir. Risk Officer olarak bu ayrımı kritik buluyorum:

**1. DD gate single-filter yeterliliği — ama bu sefer sayıların güvenilirliği de sorgulanıyor.**
LUNA DD=%35.4, FTX DD=%24.5, BTC ATH DD=%36.4 — üçü de `max_drawdown_pct: 0.20` eşiğini aşıyor. Bu tek başına VETO için yeterli. Ancak bu sayıların gerçek olduğunu varsayıyorum; adversary'nin gösterdiği gibi `final%` sayıları (%168, %252, %262, %328) bakıldığında bu varsayım çöküyor.

**2. Compounding inflation — MEMORY teyidi.**
`memory/MEMORY.md::backtest-compounding-inflation.md` notu: "gerçek champion edge ~%1-2/ay; sayılar ~10-25× şişik." Bu şişirme katsayısıyla bakıldığında: %328 final → gerçek ~%13-33. Mantıklı. Ama o zaman DD sayıları da aynı motordan geliyor — DD=%35 de 10-25x şişmiş olabilir → gerçek DD=%1.4-3.5. Bu iki uç yorumun her ikisi de kabul edilemez: **ya motor çalışıyor ve gerçek DD çok yüksek (VETO), ya da motor bozuk ve hiçbir sayıya güvenilemez (yine VETO).**

**3. LUNA recovery=1 gün, FTX recovery=6 gün — fiziksel imkânsızlık.**
Eşik `min_recovery_days_acceptable: 30`. LUNA 9-13 Mayıs 2022: %99.9 düşüş, Binance perpetual delist, likidite sıfır. Bir 15m botun bu ortamda 1 günde %35 DD'yi kapatması: ya (a) LUNA short pozisyon tutuyordu ve kâr etti — ancak bu durumda FTT/FTX delist ortamında 6 gün recovery da aynı derecede şüpheli; ya da (b) backtest motoru equity eğrisini "zamana sıfırladı" ve gerçek piyasa fiyat hareketlerini değil, suni bir kurtarma senaryosunu simüle etti. **Her iki durumda da motor forensics olmadan güvenilmez.**

**4. COVID 2020-03 = 0 trade — 5. kez, hâlâ düzeltilmedi.**
Bu tam bir survivorship bias sinyali (MEMORY: "kripto'da yıllık %20-50 etki"). Ya evren Mart 2020'de mevcut değildi → pool pipeline hâlâ tarihi kapsıyor mu? V4'te pool fix birincil unblock kriteriydi. Beş çalıştırma sonra hâlâ 0 trade → **fix yapılmadı veya yapıldı ama yanlış yapıldı.**

**5. Config (not found) — 5. kez.**
`sl_pct_min=0.025` (WIDESTOP fee-erozyon kalkanı), `max_leverage=3x` (Kaldıraç Disiplini lesson) doğrulanamıyor. `active_state` gösteriyor: bot paper (testnet) çalışıyor, uptime 2g+. **Hangi config ile çalıştığı bilinmiyor ise stress test herhangi bir config'i test ediyor — bu config ile değil.**

## Evidence

1. **DD gate: 3/4 traded period DD > %20.** LUNA %35.4, FTX %24.5 (bu eşiği aşıyor), BTC ATH %36.4. Yen Carry %11.1 (bu DD gate'i geçer ama Concave=False ile yine fail). Yalnızca DD'ye bakarak zaten 0/5.

2. **Final% sayıları MEMORY çelişiyor — motor güvenilirlik sorunu.**
   - LUNA +%168.85 (crash döneminde); FTX +%252.94; BTC ATH +%262.15; Yen Carry +%328.59
   - Compounding şişmesi katsayısı (10-25×) ile normalized gerçek değerler mantıklı görünse de, **aynı motor DD ve recovery da üretiyor** — bu sayıların da aynı sapmayla bozuk olduğu anlamına gelir.

3. **Recovery günleri istatistiksel imkânsızlık.**
   LUNA 1 gün, FTX 6 gün, BTC ATH 3 gün recovery. Bu dönemlerin spot piyasa recovery'si: LUNA = asla (delist), FTX = weeks, BTC ATH = zaten peak → motor "recovery" hesabı piyasa realitesinden kopmuş.

4. **V4 paper halt önerisi = dikkate alınmadı.**
   `active_state.md` gösteriyor: `futures_daemon_15m | paper (testnet) | 17267 | wide-stop | 2g+`. 4 CRIT, halt önerildi, bot hâlâ çalışıyor. Bu bir yönetim kararıdır — ancak bu kararın bilinçli olduğunun ve Principal'ın haberdar olduğunun teyidi gerekiyor.

5. **Adversary framing kalitesi — "0/5 yeterince ağır değil" tezi.**
   Adversary'nin temel iddiası: sorun bot değil, motor. Bu fark kritik — eğer motor bozuksa bir sonraki çalıştırmada 5/5 pass bile görsek güvenemeyiz. Gate geçme → deploy için yeterli koşul değil.

## Strengths I Want to Highlight

1. **"Ölçülemeyen risk = otomatik RED" ilkesi korundu.** Backtest motor güvenilirliği sorgulanırken CRIT verdict değişmedi. İlke erozyonu yok.

2. **Survivorship bias + compounding inflation + impossible recovery — üç bağımsız kanıt kanalı aynı anda işaret ediyor.** Bir tanesi yanlış olsa bile diğerleri yeterli. Bu derinlik adversary metodolojisinin olgunlaştığını gösteriyor.

3. **"CRIT yeterince ağır değil" framing'i.** CEO ve Principal'a iletimde doğrudan kullanılabilir: reject sebebi salt istatistik değil, motor güvenilirliği meselesi. Bu, fix scope'unu doğru tanımlıyor (backtest engine audit, sadece parametre düzeltme değil).

4. **Config (not found) + 0 trade + fantastical returns üçlüsü = stres testinin kendisini test edemiyor.**
   Bu framing önceki dört CRIT'i birleştiren ve Principal'a tek mesaj olarak iletilmesi gereken özet.

## What would change my mind

V4'teki kriterler artık MINIMUM. Beşinci CRIT sonrası ek koşullar:

1. **Backtest motor audit (YENİ — P0):** `backtest/engine.py` MaxDD hesabı equity-bazlı mı doğrulanmalı. `final%` compounding şişmesi olmadan üretildiği kanıtlanmalı. Motor audit raporuna sahip olmadan hiçbir stres test çıktısına güvenemeyiz.

2. **Pool pipeline fix kanıtı (V4'ten taşındı — P0):** COVID 2020-03'te `n_trades ≥ 3` görülmeli. Fix commit + CI test + yeni çalıştırma gerekli.

3. **Config path netleşmeli (V4'ten taşındı — P0):** Aktif config `sl_pct_min`, `max_leverage`, `position_sizing` değerleri stres test raporuna eklenecek.

4. **Recovery metriği tanımı netleşmeli (YENİ — P1):** "Recovery = kaç günde equity DD'den çıktı" mı, "recovery = piyasa fiyatı crash-öncesi seviyelere döndü" mü? İkincisi ise LUNA için tanımsız. Birincisi ise motor hesaplama kanıtı gerekiyor.

5. **5/5 dönemde `n_trades ≥ 3` + tüm gate kriterleri karşılanmalı (V4'ten sertleşti):** V4'te 3/5 yeterliydi. Beş CRIT sonrası bar yükseldi — 5/5 gerekiyor.

---

## Risk Officer Zorunlu Escalation — 5. CRIT (MANDATORY)

**CEO ve Principal'a; kopyası Ops Engineer'a:**

V4'te paper halt **öneri** idi. Principal override yazmadıysa — aktif_state'e göre yazmadı — V5 sonrası bu önerinin karşılık bulmaması **kasıtlı bilinçli risk kabulü** veya **gözetim açığı**dır. İkisi de belgelenmeli.

**Risk Officer olarak kaydediyorum:**

- **Beş ardışık CRIT** = tek seferlik hata değil, yapısal ihmal.
- **V4 paper halt önerisi görmezden gelindi** = ya "bilerek kabul ediyoruz" (Principal imzası gerekiyor) ya da "kimse takip etmedi" (ops failure).
- **Backtest motoru güvenilir değilse** paper sonuçları strateji promosyon kararlarında kanıt olarak kullanılamaz — `active_state` §3'te "Wide-stop deploy onayı" beklendiği görülüyor; bu karar kirlenmişe sayılır.

**Unblock olmadan `futures15m` paper trading devam ederse:**

> Risk Officer bu durumu **kabul edilmiş bilinçli risk** olarak loglayacak ve Principal'ın açık yazılı onayını bekleyecek. Onay gelmezse aylık KPI raporuna "gözetim açığı" olarak işlenecek.

Şişmiş backtest sonuçlarına dayanan promosyon kararları → likidasyon riski → bu şirketin en büyük öğrenilmemiş dersi.
