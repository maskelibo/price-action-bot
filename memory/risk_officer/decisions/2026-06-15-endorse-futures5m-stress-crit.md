---
doc_id: risk_officer-20260615T041500-endorse-futures5m-stress-crit
doc_type: endorse
agent_id: risk_officer
created_at: 2026-06-15T04:15:00Z
status: PROPOSED
confidence: high
depends_on: [adversary_engineer-20260615T040117-stress-2026-06-15-futures5m]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures5m, crit, deployment_block]
supersedes: null
---

ENDORSE

## Claim

Adversary Engineer, futures5m stratejisinin 5 tarihsel kaskat penceresinin tamamında (0/5) stress test'ten geçemediğini; bunların içinde LUNA 2022-05'te hesabın trade 772'de tam likidasyona uğradığını (DD %100) kanıtlamıştır. CRIT etiketi doğrudur.

## Why I Endorse

Risk Officer olarak Adversary Engineer'ın CRIT kararını **tam anlamıyla** destekliyorum ve buna **deployment BLOCK** ekliyorum. Gerekçe iki katmanlı:

**Katman 1 — Tek başına kilitleyici (LUNA):** Bir stratejinin en kötü tarihsel kriz penceresinde sermayenin %100'ünü yok etmesi, o stratejinin canlı hiçbir yapıda —testnet dahil gerçek para ile— kullanılamayacağını gösterir. DD eşiği %20; gerçek sonuç %100. Bu 5× aşım değil: **kategorik farklı bir risk sınıfı.** Margin call hayatta kalmayı fırsata çevirmek "final return pozitif çıkabilirdi" iddiasını geçersiz kılar — hesap trade 772'de sıfırlanmışsa, sonraki 3130 trade **reel olmayan** spekülatif iz.

**Katman 2 — Likidite körü (COVID + slippage):** COVID 2020-03'te sıfır trade, stratejinin extreme volatilite rejimini kör geçtiğini gösterir. 5m grain'de tek bar bile anormalde tüm equity'yi silebilir — Adversary bu noktayı doğru vurguluyor. Paper journal bu senaryoyu kayıt edemez; gerçek fillslippage kör nokta.

Sonuç: **futures5m, hiçbir bant veya yorum altında canlıya taşınamaz.** Active state kontrolü: 5m P1c şu an "Principal sign-off PENDING, paper-only" — bu CRIT bulgu deploy kapısını kapatır.

## Evidence

| Period | DD% | Gate (0.20) | Yorum |
|---|---|---|---|
| LUNA 2022-05 | **100.0** | FAIL ×5 | Tam likidasyon trade 772; hesap yoktu. |
| FTX 2022-11 | 84.28 | FAIL ×4.2 | Equity altıda biri kaldı — margincall gerçekte gelirdi. |
| BTC ATH 2024-03 | 66.83 | FAIL ×3.3 | 2/3 sermaye yanmış; +648% final return aldatıcı. |
| Yen Carry 2024-08 | 23.79 | FAIL ×1.2 | Tek günde -%15 kripto; fill kalitesi backtest'te yok. |
| COVID 2020-03 | N/A (0 trade) | — | Sinyal sığlığı = rejim körlüğü. |

**Ek risk bulgum — Gate logic tutarsızlığı:**
LUNA satırında `Recov d: None` ve `Final%: -100.0` olmasına rağmen `Recov Gate: True` görünüyor. Likidasyon sonrası recovery tanımlanamaz, bu gate'in `True` dönmemesi gerekir. Bu tutarsızlık CRIT kararını değiştirmiyor (DD gate zaten FAIL) ama **recovery gate implementasyonunda bir mantık hatası var** — ops_engineer'a ayrıca iletilmeli.

**Ek risk bulgum — Config bulunamadı:**
Stress test `config: (not found)` ile koşulmuş. Yani gerçek leverage/sizing parametreleri bilinmiyor; kriz senaryosu default ya da varsayımsal config ile test edilmiş. Bu, bulunan sonuçların bile **en iyi senaryo** olabileceğini ima eder (eğer gerçek config daha agresif sizing kullanıyorsa DD daha kötüdür).

## Strengths I Want to Highlight

1. **"Pozitif final return" tuzağına düşmeme:** Adversary, FTX +208% ve BTC ATH +648% rakamlarını gerçekçi değil spekülatif iz olarak doğru etiketledi. Risk Officer aynı tutumu paylaşır: margin call'dan sonra hayatta kalan hesap yoktu.

2. **Slippage körü teşhisi:** 5m timeframe'de bir kaskat günü likidite tabakası çekildiğinde backtest fill ile gerçek fill arasındaki delta yüzde cinsinden ölçülebilir. Bu fark stress testine dahil edilmemiş — Adversary bunu "kör nokta" olarak doğru işaretledi.

3. **COVID sıfır-trade uyarısı:** Strateji bir extreme volalite penceresi boyunca sinyal üretemiyorsa, **bilinmeyen bir kuyruk riskini taşıyor demektir.** "Zarar etmedi çünkü girmedi" değil — "ne yapacağını bilmiyordu, şans eseri kurtuldu."

4. **Eşiklerle orantılı ciddiyetin doğru kalibrasyonu:** `max_drawdown_pct_per_period: 0.20` eşiği Risk.yaml ile tutarlı (bkz. shared/lessons kaldıraç disiplini). Adversary bu parametreyi doğru uygulamış.

## What would change my mind

Tek senaryo: futures5m'in gerçek deployed config'inde (şu an "not found") **LUNA günlük DD >-5% → otomatik flatten** gibi bir breaker mekanizması aktifse ve bu mekanizmanın LUNA stres koşullarında (likidasyon fiyatı <1 saniye içinde %50 gap) **fill garantisi** sağlandığı kanıtlanırsa, LUNA senaryosu revize edilebilir. Ama diğer 4 pencerede de gate aşımı var; tek bir breaker kanıtı tüm CRIT'i kaldırmaz.

Kısaca: **futures5m deploy kanalı kapalıdır.** Strateji bu haliyle lab'a bile alınmamalı; önce kriz rejimi filtreleme + breaker mekanizması tasarlanmalı, sonra stress test yeniden koşulmalıdır.
